"""Process-wide flag shared by agents.py and inspect_agent.py so both know
when the principal model's daily quota is exhausted, instead of each one
rediscovering it independently with a wasted request."""

principal_quota_exhausted = False
