"""Local test — render the bracket and save to disk."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from services.bracket import (
    MATCHES_PATH,
    load_local_matches,
    build_bracket_data,
    render_png,
)

OUTPUT = os.path.join(os.path.dirname(__file__), "bracket_test.png")


def main():
    local = load_local_matches()
    print(f"Loaded {len(local)} local matches")

    ko = build_bracket_data(local)
    scored = [m for m in ko if m.get("score")]
    print(f"Built {len(ko)} knockout matches ({len(scored)} with scores)")

    png = render_png(ko)
    with open(OUTPUT, "wb") as f:
        f.write(png)
    print(f"Saved {len(png)} bytes to {OUTPUT}")


if __name__ == "__main__":
    main()
