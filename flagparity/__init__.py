"""FlagParity (working name until Phase 3: FlagBound) — offline, deterministic verifier for feature-flag definition files.

Phase 1 core. Pure functions over file bytes; no network, no clock, no global state.
"""
TOOL_VERSION = "0.1.0-phase1"
OUTPUT_SCHEMA = "flagparity.verdict/v1"
INPUT_SCHEMA = "flagparity.request/v1"
