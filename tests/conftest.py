"""Test infrastructure for content-pipeline-stack.
Iron Rule v249 + Phase 0 first-principles: chokepoint async_req needs unit test coverage.
"""
import sys
from pathlib import Path

# Add source/ to sys.path so tests can import cps modules
SRC = Path(__file__).resolve().parent.parent / "services/douyin-recorder/source"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
