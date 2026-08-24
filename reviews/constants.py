from decimal import Decimal

#Rating weights
WEIGHT_COMMUNICATION = Decimal("0.30")
WEIGHT_PUNCTUALITY = Decimal("0.30")
WEIGHT_QUALITY = Decimal("0.40")

#Review eligibility
REVIEW_WINDOW_DAYS = 14
EDIT_WINDOW_HOURS= 24
RESPONSE_WINDOW_DAYS =30

# Discovery thresholds
TOP_RATED_MIN_AVERAGE = Decimal("4.0")
TOP_RATED_MIN_REVIEWS = 5
LOW_RATING_THRESHOLD = Decimal("2.5")
LOW_RATING_MIN_REVIEWS = 5
PUBLIC_RATING_MIN = 3

# spike detection
SPIKE_WINDOW_HOURS = 24
SPIKE_COUNT = 5