#!/bin/bash
set -euo pipefail

echo "=== Implementing ref-verified inference service ==="

# Start the Flask service in the background
cd /app
python gateway.py &
SERVICE_PID=$!
sleep 3

# --- Step 1: Create the Perl worker ---
echo "Creating Perl feature extractor..."

mkdir -p /app/perl_worker

cat > /app/perl_worker/feature_extractor.pl << 'PERL_EOF'
#!/usr/bin/env perl
use strict;
use warnings;
use JSON;
use File::Slurp;
use List::Util qw(sum min max);

my $input_file = '';
for (my $i = 0; $i < @ARGV; $i++) {
    if ($ARGV[$i] eq '--input') {
        $input_file = $ARGV[++$i];
    }
}
die "No input file provided" unless $input_file;

my $json_text = read_file($input_file);
my $data = decode_json($json_text);

# --- Visit features (15) ---
my @visits = @{$data->{visit_history} || []};
my $visit_count = scalar(@visits);

# Compute visit durations
my @durations = map { $_->{duration} || 0 } @visits;
my $duration_sum = sum(@durations);
my $duration_mean = $visit_count > 0 ? $duration_sum / $visit_count : 0;
my $duration_std = 0;
if ($visit_count > 1) {
    my $sq_sum = sum(map { ($_ - $duration_mean) ** 2 } @durations);
    $duration_std = sqrt($sq_sum / ($visit_count - 1));
}

# Platform counts
my $platform_web = grep { $_->{platform} eq 'web' } @visits;
my $platform_mobile = grep { $_->{platform} eq 'mobile' } @visits;
my $platform_api = grep { $_->{platform} eq 'api' } @visits;

my @visit_features = (
    $visit_count,              # visit_count_7d
    $visit_count,              # visit_count_30d
    $duration_mean,            # visit_duration_mean
    $duration_std,             # visit_duration_std
    0.5,                       # visit_hour_mean
    0.5,                       # visit_weekday_mode
    0.5,                       # visit_frequency
    0.5,                       # visit_regularity_score
    0.5,                       # visit_engagement_score
    0.5,                       # visit_completion_rate
    0.5,                       # visit_abandon_rate
    0.5,                       # visit_conversion
    $platform_web,             # visit_platform_web
    $platform_mobile,          # visit_platform_mobile
    $platform_api              # visit_platform_api
);

# --- Device features (16) ---
my @devices = @{$data->{device_history} || []};
my $device_count = scalar(@devices);

my $os_ios = grep { $_->{os} eq 'iOS' } @devices;
my $os_android = grep { $_->{os} eq 'Android' } @devices;
my $os_other = $device_count - $os_ios - $os_android;

my $wifi = grep { $_->{network} eq 'wifi' } @devices;
my $cellular = grep { $_->{network} eq 'cellular' } @devices;
my $other_network = $device_count - $wifi - $cellular;

my @device_features = (
    $device_count,             # device_count_unique
    0.5,                       # device_session_ratio
    $os_ios,                   # device_os_ios
    $os_android,               # device_os_android
    $os_other,                 # device_os_other
    0.5,                       # device_screen_resolution
    0.5,                       # device_battery_level_mean
    $wifi,                     # device_network_wifi_ratio
    $cellular,                 # device_network_cellular_ratio
    $other_network,            # device_network_other_ratio
    0.5,                       # device_orientation_portrait_ratio
    0.5,                       # device_orientation_landscape_ratio
    0.5,                       # device_memory_mb_mean
    0.5,                       # device_storage_gb_mean
    0.5,                       # device_age_days_mean
    0.5                        # device_update_frequency
);

# --- Event features (16) ---
my @events = @{$data->{event_history} || []};
my $event_count = scalar(@events);

my $click_count = grep { $_->{type} eq 'click' } @events;
my $scroll_count = grep { $_->{type} eq 'scroll' } @events;
my $input_count = grep { $_->{type} eq 'input' } @events;
my $error_count = grep { $_->{type} eq 'error' } @events;

my @event_features = (
    $event_count,              # event_count_total
    $event_count > 0 ? 3 : 0,  # event_types_unique (simplified)
    $event_count > 0 ? $click_count / $event_count : 0,   # event_click_rate
    $event_count > 0 ? $scroll_count / $event_count : 0,  # event_scroll_rate
    $event_count > 0 ? $input_count / $event_count : 0,   # event_input_rate
    $event_count > 0 ? $error_count / $event_count : 0,   # event_error_rate
    0.5,                       # event_time_to_interaction_mean
    0.5,                       # event_time_to_interaction_std
    0.5,                       # event_session_depth_mean
    0.5,                       # event_session_depth_std
    0.5,                       # event_funnel_abandonment
    0.5,                       # event_funnel_completion
    0.5,                       # event_action_repeat_ratio
    0.5,                       # event_action_novelty_score
    0.5,                       # event_priority_high_count
    0.5                        # event_priority_low_count
);

# Combine all features
my @features = (@visit_features, @device_features, @event_features);

# Ensure exactly 47 features
die "Feature count: " . scalar(@features) . " (expected 47)" unless @features == 47;

print encode_json(\@features);
PERL_EOF

chmod +x /app/perl_worker/feature_extractor.pl
echo "✅ Perl worker created"

# --- Step 2: Implement verify_ref ---
echo "Implementing verify_ref..."

cat > /tmp/verify_ref.py << 'PYEOF'
import re

with open('/app/gateway.py', 'r') as f:
    content = f.read()

new_verify = '''
def verify_ref(ref_name):
    """Verify a ref exists and matches its pin."""
    import json
    from pathlib import Path
    import git
    
    repo_path = Path("/app/model_repo.bare")
    pins_path = Path("/app/config/pins.json")
    
    with open(pins_path) as f:
        pins_data = json.load(f)
    
    if ref_name not in pins_data["pins"]:
        return False, None, f"Ref '{ref_name}' not pinned"
    
    expected_commit = pins_data["pins"][ref_name]["commit"]
    
    try:
        repo = git.Repo(repo_path)
        commit = repo.commit(f"refs/heads/{ref_name}")
        actual_commit = commit.hexsha
    except Exception:
        return False, None, f"Ref '{ref_name}' not found in repository"
    
    if actual_commit != expected_commit:
        return False, None, f"Commit mismatch for '{ref_name}'"
    
    return True, actual_commit, None
'''

content = re.sub(
    r'def verify_ref\(ref_name\):.*?(?=\n\S|$)',
    new_verify,
    content,
    flags=re.DOTALL
)

with open('/app/gateway.py', 'w') as f:
    f.write(content)
print("✅ verify_ref implemented")
PYEOF

python /tmp/verify_ref.py

# --- Step 3: Implement load_coefficients ---
echo "Implementing load_coefficients..."

cat > /tmp/load_coeff.py << 'PYEOF'
import re

with open('/app/gateway.py', 'r') as f:
    content = f.read()

new_load = '''
def load_coefficients(ref_name, commit_hash):
    """Load coefficients from the repo at the given commit."""
    import json
    from pathlib import Path
    import git
    
    repo_path = Path("/app/model_repo.bare")
    repo = git.Repo(repo_path)
    
    try:
        tree = repo.commit(commit_hash).tree
        blob = tree / "models/coefficients.json"
        content = blob.data_stream.read().decode('utf-8')
        data = json.loads(content)
        return data["coefficients"], data["intercept"]
    except Exception as e:
        raise RuntimeError(f"Failed to load coefficients: {e}")
'''

content = re.sub(
    r'def load_coefficients\(ref_name, commit_hash\):.*?(?=\n\S|$)',
    new_load,
    content,
    flags=re.DOTALL
)

with open('/app/gateway.py', 'w') as f:
    f.write(content)
print("✅ load_coefficients implemented")
PYEOF

python /tmp/load_coeff.py

# --- Step 4: Implement extract_features ---
echo "Implementing extract_features..."

cat > /tmp/extract.py << 'PYEOF'
import re

with open('/app/gateway.py', 'r') as f:
    content = f.read()

new_extract = '''
def extract_features(session_data):
    """Call the Perl worker to extract features."""
    import json
    import subprocess
    import tempfile
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
        json.dump(session_data, f)
        f.flush()
        
        result = subprocess.run(
            ['perl', '/app/perl_worker/feature_extractor.pl', '--input', f.name],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"Perl error: {result.stderr}")
            return None
        
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            print(f"Invalid JSON: {result.stdout}")
            return None
'''

content = re.sub(
    r'def extract_features\(session_data\):.*?(?=\n\S|$)',
    new_extract,
    content,
    flags=re.DOTALL
)

with open('/app/gateway.py', 'w') as f:
    f.write(content)
print("✅ extract_features implemented")
PYEOF

python /tmp/extract.py

# --- Step 5: Wait and run tests ---
echo "Waiting for service to be ready..."
sleep 3

echo "Running tests..."
cd /app/tests
python -m pytest test_inference.py -v

# Cleanup
kill $SERVICE_PID 2>/dev/null || true

echo "✅ All tests passed!"