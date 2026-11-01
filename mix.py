#!/usr/bin/env python3
"""Mixed-engine videos: each segment from reel, animate, Remotion, HyperFrames or a file, stitched into one.
Usage: python run.py mix plan.json [--reuse] [--only 2,3]. See reelkit/mix.py for the plan format."""
from reelkit.mix import main

if __name__ == "__main__":
    main()
