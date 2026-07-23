#!/usr/bin/perl
use strict;
use warnings;
use JSON::PP qw(decode_json encode_json);
use File::Temp qw(tempdir);
use POSIX qw(strftime);

use constant {
    CONTRACT_PATH => '/app/contract/feature_contract.json',
    LOCKFILE_PATH => '/app/config/model.lock.json',
    REPO_PATH     => '/app/model.git',
};

sub read_all_stdin {
    local $/;
    return <STDIN>;
}

sub fail {
    my ($code, $error, $detail) = @_;
    print STDOUT encode_json({ error => $error, detail => $detail });
    print STDOUT "\n";
    exit $code;
}

sub read_json_file {
    my ($path) = @_;
    open(my $fh, '<', $path) or fail(2, 'internal_error', "cannot open $path: $!");
    local $/;
    my $raw = <$fh>;
    close $fh;
    return decode_json($raw);
}

# -- 1. parse request -------------------------------------------------------
my $raw_input = read_all_stdin();
my $req;
eval { $req = decode_json($raw_input); 1 } or fail(2, 'bad_request', 'request body is not valid JSON');

fail(2, 'bad_request', 'missing "model_ref"') unless defined $req->{model_ref} && length $req->{model_ref};
fail(2, 'bad_request', 'missing "session"')   unless ref $req->{session} eq 'HASH';

my $model_ref = $req->{model_ref};
my $session   = $req->{session};

# -- 2. ref pinning check ----------------------------------------------------
my $lock = read_json_file(LOCKFILE_PATH);
fail(3, 'unpinned_ref', "ref '$model_ref' is not present in the pinned lockfile")
    unless exists $lock->{$model_ref};
my $expected_sha = $lock->{$model_ref};

# -- 3. clone + fetch the requested ref, verify it matches the pin ---------
my $tmpdir = tempdir(CLEANUP => 1);
my $clone_rc = system("git clone --quiet " . REPO_PATH . " '$tmpdir' >/dev/null 2>&1");
fail(2, 'internal_error', 'failed to clone model repository') if $clone_rc != 0;

my $fetch_rc = system("git -C '$tmpdir' fetch --quiet origin '$model_ref' >/dev/null 2>&1");
fail(2, 'internal_error', "failed to fetch ref '$model_ref' from model repository") if $fetch_rc != 0;

my $actual_sha = `git -C '$tmpdir' rev-parse FETCH_HEAD 2>/dev/null`;
chomp $actual_sha;
fail(2, 'internal_error', 'could not resolve fetched ref') unless $actual_sha =~ /^[0-9a-f]{40}$/;

if ($actual_sha ne $expected_sha) {
    fail(4, 'ref_mismatch',
        "ref '$model_ref' resolved to $actual_sha but the pinned commit is $expected_sha");
}

# -- 4. load coefficients from the exact pinned commit ----------------------
my $coeff_raw = `git -C '$tmpdir' show '$actual_sha:coefficients.json' 2>/dev/null`;
fail(2, 'internal_error', 'coefficients.json missing at pinned commit') unless length $coeff_raw;

my $coeffs;
eval { $coeffs = decode_json($coeff_raw); 1 } or fail(2, 'internal_error', 'coefficients.json is not valid JSON');
fail(2, 'internal_error', 'coefficients.json missing "bias"')   unless defined $coeffs->{bias};
fail(2, 'internal_error', 'coefficients.json missing "weights"') unless ref $coeffs->{weights} eq 'HASH';

# -- 5. load contract, validate coefficient coverage -------------------------
my $contract = read_json_file(CONTRACT_PATH);
my @features = @{ $contract->{features} };

my %contract_names = map { $_->{name} => 1 } @features;
my %weight_names    = map { $_ => 1 } keys %{ $coeffs->{weights} };

my @missing = grep { !exists $weight_names{$_} } keys %contract_names;
my @extra   = grep { !exists $contract_names{$_} } keys %weight_names;

if (@missing || @extra) {
    my $detail = '';
    $detail .= 'missing: ' . join(',', sort @missing) . ' ' if @missing;
    $detail .= 'unexpected: ' . join(',', sort @extra) if @extra;
    fail(5, 'incomplete_coefficients', $detail);
}

# -- 6. flatten the session per the contract ---------------------------------
my $patient = $session->{patient} // {};
my @visits  = @{ $session->{visits}  // [] };
my @devices = @{ $session->{devices} // [] };
my @events  = @{ $session->{events}  // [] };

my %computed;
$computed{patient_age}   = defined $patient->{age} ? $patient->{age} + 0.0 : undef;
$computed{patient_sex_f} = (defined $patient->{sex} && $patient->{sex} eq 'F') ? 1.0 : 0.0;

$computed{visit_count}    = scalar(@visits);
$computed{visit_ed_count} = scalar(grep { defined $_->{type} && $_->{type} eq 'ed' } @visits);

{
    my @acuities = grep { defined $_ } map { $_->{acuity} } @visits;
    $computed{visit_acuity_max} = @acuities ? (sort { $b <=> $a } @acuities)[0] : undef;
}

{
    my $total = 0;
    for my $v (@visits) {
        $total += $v->{duration_min} if defined $v->{duration_min};
    }
    $computed{visit_duration_total} = $total; # sum over zero visits is legitimately 0.0
}

{
    my @spo2_values;
    for my $d (@devices) {
        for my $r (@{ $d->{readings} // [] }) {
            push @spo2_values, $r->{value} if defined $r->{metric} && $r->{metric} eq 'spo2' && defined $r->{value};
        }
    }
    $computed{device_spo2_min} = @spo2_values ? (sort { $a <=> $b } @spo2_values)[0] : undef;
}

$computed{event_count} = scalar(@events);

{
    my @severities = grep { defined $_ } map { $_->{severity} } @events;
    $computed{event_severity_max} = @severities ? (sort { $b <=> $a } @severities)[0] : undef;
}

$computed{event_triage_escalation_present} =
    (grep { defined $_->{code} && $_->{code} eq 'triage_escalation' } @events) ? 1.0 : 0.0;

# -- 7. build the ordered feature vector, applying contract defaults --------
my @feature_names;
my @x;
for my $f (@features) {
    my $name    = $f->{name};
    my $default = $f->{default};
    my $val     = $computed{$name};
    $val = $default unless defined $val;
    push @feature_names, $name;
    push @x, $val + 0.0;
}

# -- 8. score -----------------------------------------------------------------
my $z = $coeffs->{bias} + 0.0;
for my $i (0 .. $#feature_names) {
    my $name = $feature_names[$i];
    $z += $coeffs->{weights}{$name} * $x[$i];
}
my $score = 1.0 / (1.0 + exp(-$z));
my $score_rounded = sprintf('%.6f', $score) + 0.0;
my $label = ($score >= 0.5) ? 1 : 0;

# -- 9. respond ----------------------------------------------------------------
my $response = {
    score      => $score_rounded,
    label      => $label,
    provenance => {
        model_ref        => $model_ref,
        model_commit      => $actual_sha,
        contract_version => $contract->{contract_version},
    },
};

print STDOUT encode_json($response);
print STDOUT "\n";
exit 0;
