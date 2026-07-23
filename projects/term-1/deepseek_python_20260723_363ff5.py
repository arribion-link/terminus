"""
Polars feature contract - 47 features expected from Perl worker.
"""
import polars as pl

FEATURE_NAMES = [
    # Visit features (15)
    'visit_count_7d', 'visit_count_30d', 'visit_duration_mean',
    'visit_duration_std', 'visit_hour_mean', 'visit_weekday_mode',
    'visit_frequency', 'visit_regularity_score', 'visit_engagement_score',
    'visit_completion_rate', 'visit_abandon_rate', 'visit_conversion',
    'visit_platform_web', 'visit_platform_mobile', 'visit_platform_api',
    # Device features (16)
    'device_count_unique', 'device_session_ratio', 'device_os_ios',
    'device_os_android', 'device_os_other', 'device_screen_resolution',
    'device_battery_level_mean', 'device_network_wifi_ratio',
    'device_network_cellular_ratio', 'device_network_other_ratio',
    'device_orientation_portrait_ratio', 'device_orientation_landscape_ratio',
    'device_memory_mb_mean', 'device_storage_gb_mean', 'device_age_days_mean',
    'device_update_frequency',
    # Event features (16)
    'event_count_total', 'event_types_unique', 'event_click_rate',
    'event_scroll_rate', 'event_input_rate', 'event_error_rate',
    'event_time_to_interaction_mean', 'event_time_to_interaction_std',
    'event_session_depth_mean', 'event_session_depth_std',
    'event_funnel_abandonment', 'event_funnel_completion',
    'event_action_repeat_ratio', 'event_action_novelty_score',
    'event_priority_high_count', 'event_priority_low_count'
]

def validate_features(features):
    if not isinstance(features, list):
        return False
    if len(features) != 47:
        return False
    if not all(isinstance(x, (int, float)) for x in features):
        return False
    return True