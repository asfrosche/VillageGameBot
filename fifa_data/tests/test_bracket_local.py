"""Local test — render the bracket and save to disk."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(__file__) + "/..")
from fifa_data.services.bracket import (
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

    # Dark variant
    dark_out = OUTPUT.replace(".png", "_dark.png")
    png_dark = render_png(ko, style="dark")
    with open(dark_out, "wb") as f:
        f.write(png_dark)
    print(f"Saved {len(png_dark)} bytes to {dark_out}")


if __name__ == "__main__":
    main()
