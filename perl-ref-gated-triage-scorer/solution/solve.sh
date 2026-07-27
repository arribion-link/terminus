#!/usr/bin/env bash
set -euo pipefail

cat > /app/worker/triage_worker.pl << 'PERLEOF'
#!/usr/bin/perl
use strict;
use warnings;
use JSON::PP qw(decode_json encode_json);
use Digest::SHA qw(sha256_hex);
use Time::Piece;
use POSIX qw(ceil floor);

$| = 1;

my $stdin = do { local $/; <STDIN> };
my $job = decode_json($stdin);

# ping
if ($job->{op} eq 'ping') {
    print encode_json({ok => JSON::PP::true}) . "\n";
    exit 0;
}

my $payload = $job->{payload} // {};
my $model_ref = $job->{model_ref} // '';

# validate payload schema
if (!defined $payload->{session_start} || ref $payload->{session_start}) {
    emit_err('INVALID_PAYLOAD', 'missing or invalid session_start');
}
for my $key (qw(visits devices events)) {
    if (defined $payload->{$key} && ref($payload->{$key}) ne 'ARRAY') {
        emit_err('INVALID_PAYLOAD', "field $key must be a JSON array");
    }
}

# --- IPC helpers ---
sub emit_err { my ($code, $msg) = @_; print encode_json({ok => JSON::PP::false, error_code => $code, message => $msg}) . "\n"; exit 0; }

# --- feature config ---
my @FEAT_ORDER = qw(n_visits hr_mean hr_max spo2_min bp_sys_mean visit_recency_weight night_visit_ratio n_events_weighted n_fall_events n_distinct_devices device_span_hours hr_slope_per_hour);
my $FEAT_HASH = substr(sha256_hex(join(',', @FEAT_ORDER)), 0, 12);

# --- timestamp parser ---
sub iso_to_epoch {
    my ($s) = @_;
    $s =~ s/Z$//;
    $s =~ s/\+00:00$//;
    my ($date, $time) = split(/T/, $s, 2);
    my @d = split(/-/, $date);
    my @t = split(/:/, $time);
    my $dt = Time::Piece->strptime(join('T', join('-', @d), join(':', @t)) . 'Z', '%Y-%m-%dT%H:%M:%SZ');
    return int($dt->epoch);
}

# --- feature computation ---
sub features {
    my ($payload) = @_;
    my $sess_ts = iso_to_epoch($payload->{session_start});

    my @visits = ();
    for my $v (@{$payload->{visits} // []}) {
        my $ts = iso_to_epoch($v->{ts});
        next if $ts > $sess_ts;
        push @visits, { %$v, _ts => $ts };
    }
    my @events = ();
    for my $e (@{$payload->{events} // []}) {
        my $ts = iso_to_epoch($e->{ts});
        next if $ts > $sess_ts;
        push @events, { %$e, _ts => $ts };
    }
    my @devices = ();
    for my $d (@{$payload->{devices} // []}) {
        my $ts = iso_to_epoch($d->{first_seen});
        next if $ts > $sess_ts;
        push @devices, { %$d, _ft => $ts };
    }

    my %f = (
        n_visits => scalar(@visits),
    );

    my @hr_vals = ();
    for my $v (@visits) {
        if (defined $v->{heart_rate} && $v->{heart_rate} =~ /^-?(?:\d+\.?\d*|\.\d+)$/) {
            push @hr_vals, $v->{heart_rate} + 0;
        }
    }
    if (@hr_vals) {
        my $sum = 0; $sum += $_ for @hr_vals;
        $f{hr_mean} = $sum / scalar(@hr_vals);
        $f{hr_max} = (sort { $b <=> $a } @hr_vals)[0];
    } else {
        $f{hr_mean} = 70.0;
        $f{hr_max} = 70.0;
    }

    $f{hr_slope_per_hour} = 0.0;
    if (@hr_vals >= 2) {
        my @pairs = ();
        for my $v (@visits) {
            if (defined $v->{heart_rate} && $v->{heart_rate} =~ /^-?(?:\d+\.?\d*|\.\d+)$/) {
                push @pairs, [$v->{_ts} + 0, $v->{heart_rate} + 0];
            }
        }
        my $t0 = $pairs[0][0];
        my @xy = map { [($pairs[$_][0] - $t0) / 3600.0, $pairs[$_][1]] } 0..$#pairs;
        my $n = scalar(@xy);
        my ($Sx, $Sy, $Sxx, $Sxy) = (0,0,0,0);
        for my $p (@xy) {
            $Sx += $p->[0]; $Sy += $p->[1];
            $Sxx += $p->[0] ** 2; $Sxy += $p->[0] * $p->[1];
        }
        my $den = $n * $Sxx - $Sx * $Sx;
        if ($den != 0) {
            my $max_t = (sort { $b <=> $a } map { $_->[0] } @xy)[0];
            my $min_t = (sort { $a <=> $b } map { $_->[0] } @xy)[0];
            if ($max_t != $min_t) {
                $f{hr_slope_per_hour} = ($n * $Sxy - $Sx * $Sy) / $den;
            }
        }
    }

    my @spo2 = ();
    for my $v (@visits) {
        if (defined $v->{spo2} && $v->{spo2} =~ /^-?(?:\d+\.?\d*|\.\d+)$/) {
            push @spo2, $v->{spo2} + 0;
        }
    }
    $f{spo2_min} = @spo2 ? (sort { $a <=> $b } @spo2)[0] : 97.0;

    my @bp = ();
    for my $v (@visits) {
        if (defined $v->{bp_sys} && $v->{bp_sys} =~ /^-?(?:\d+\.?\d*|\.\d+)$/) {
            push @bp, $v->{bp_sys} + 0;
        }
    }
    if (@bp) {
        my $s = 0; $s += $_ for @bp;
        $f{bp_sys_mean} = $s / scalar(@bp);
    } else {
        $f{bp_sys_mean} = 120.0;
    }

    my $rec = 0.0;
    for my $v (@visits) {
        my $ah = ($sess_ts - $v->{_ts}) / 3600.0;
        $rec += exp(-$ah / 48.0);
    }
    $f{visit_recency_weight} = $rec;

    my $night = 0;
    for my $v (@visits) {
        my ($h) = (gmtime($v->{_ts}))[2];
        if ($h == 22 || $h == 23 || ($h >= 0 && $h <= 5)) {
            $night++;
        }
    }
    $f{night_visit_ratio} = @visits ? $night / scalar(@visits) : 0.0;

    my $ew = 0.0;
    for my $e (@events) {
        my $sev = (defined $e->{severity} && $e->{severity} =~ /^-?(?:\d+\.?\d*|\.\d+)$/) ? $e->{severity} + 0 : 1;
        my $ah = ($sess_ts - $e->{_ts}) / 3600.0;
        $ew += $sev * exp(-$ah / 24.0);
    }
    $f{n_events_weighted} = $ew;

    my $fcount = 0;
    for my $e (@events) {
        $fcount++ if (defined $e->{type} && $e->{type} eq 'fall_detected');
    }
    $f{n_fall_events} = $fcount;

    my %dedup = ();
    for my $d (@devices) {
        my $name = $d->{name} // '';
        $name = lc($name);
        $name =~ s/[^a-z0-9]+/ /g;
        $name =~ s/^\s+|\s+$//g;
        $dedup{$name} = 1 if $name ne '';
    }
    $f{n_distinct_devices} = scalar(keys %dedup);

    my $max_span = 0.0;
    for my $d (@devices) {
        my $ft = $d->{_ft};
        my $eff = $sess_ts;
        if (defined $d->{last_seen}) {
            my $ls = iso_to_epoch($d->{last_seen});
            $eff = $ls < $sess_ts ? $ls : $sess_ts;
        }
        my $span = ($eff - $ft) / 3600.0;
        $span = 0.0 if $span < 0;
        $max_span = $span if $span > $max_span;
    }
    $f{device_span_hours} = $max_span;

    return \%f;
}

# --- scoring ---
sub compute_score {
    my ($coeffs, $intercept, $features) = @_;
    my $z = $intercept;
    for my $fn (@FEAT_ORDER) {
        $z += ($coeffs->{$fn} // 0) * ($features->{$fn} // 0);
    }
    $z = -40.0 if $z < -40.0;
    $z = 40.0 if $z > 40.0;
    my $p = 1.0 / (1.0 + exp(-$z));
    return $p;
}

# --- ref resolution ---
sub resolve_ref {
    my ($ref) = @_;
    my $repo = $ENV{MODEL_REPO_PATH} // '/srv/model-repo.git';
    my $work = "/tmp/model_check_$$";
    system("git", "clone", $repo, $work) == 0 or emit_err('SERVICE_ERROR', 'cannot clone model repo');

    # collect advertised commit set (peeled)
    my %advertised;
    open(my $list, '-|', 'git', '-C', $work, 'for-each-ref', '--format=%(objecttype) %(refname)') or emit_err('SERVICE_ERROR', 'cannot enumerate refs');
    while (my $line = <$list>) {
        chomp $line;
        next unless $line =~ /^(commit|tag)\s+(refs\/.+\S+)/;
        my ($type, $refname) = ($1, $2);
        if ($type eq 'commit') {
            my $sha = `git -C $work rev-parse '$refname'`; chomp $sha;
            $advertised{$sha} = 1;
        } elsif ($type eq 'tag') {
            my $peeled = `git -C $work rev-parse '$refname^{commit}'`; chomp $peeled;
            $advertised{$peeled} = 1;
        }
    }
    close $list;

    if ($ref =~ /^[0-9a-f]{40}$/) {
        if (!exists $advertised{$ref}) {
            system("rm", "-rf", $work);
            emit_err('REF_MISMATCH', "SHA $ref is not an advertised ref");
        }
        return ($work, $ref, 'commit');
    } elsif ($ref =~ /^v\d+\.\d+\.\d+$/) {
        my $tagtype = `git -C $work cat-file -t refs/tags/$ref 2>/dev/null`; chomp $tagtype;
        if ($tagtype eq 'tag') {
            my $peeled = `git -C $work rev-parse 'refs/tags/$ref^{commit}'`; chomp $peeled;
            return ($work, $peeled, 'tag');
        } else {
            system("rm", "-rf", $work);
            emit_err('UNPINNED_REF', "tag $ref is not an annotated tag");
        }
    } else {
        system("rm", "-rf", $work);
        emit_err('UNPINNED_REF', "ref $ref is not a valid pinned ref or annotated tag");
    }
}

# --- main ---
my ($work, $commit, $ref_kind) = resolve_ref($model_ref);

my $model_raw = `git -C $work show $commit:model.json 2>/dev/null`; chomp $model_raw;
if (!$model_raw) {
    system("rm", "-rf", $work);
    emit_err('REF_MISMATCH', "model.json not found at commit $commit");
}
my $model = decode_json($model_raw);
my $coeffs = $model->{coefficients} // {};
my $intercept = $model->{intercept} // 0;
my $version = $model->{model_version} // 'unknown';

system("rm", "-rf", $work);

my $feats = features($payload);
my $score = compute_score($coeffs, $intercept, $feats);

my $resp = {
    ok           => JSON::PP::true,
    score        => sprintf("%.6f", $score) + 0,
    model_commit => $commit,
    ref_kind     => $ref_kind,
    model_version => $version,
    feature_order_hash => $FEAT_HASH,
    features     => $feats,
};
print encode_json($resp) . "\n";
exit 0;
PERLEOF

chmod +x /app/worker/triage_worker.pl
