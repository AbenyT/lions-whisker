"""Validate storyboard.json against schema/storyboard.schema.json and print a summary."""
from common import load_storyboard

if __name__ == "__main__":
    sb = load_storyboard()
    words = sum(len(s["narration"]["en"].split()) for s in sb["shots"])
    print(f"storyboard OK: {len(sb['shots'])} shots, {len(sb['characters'])} characters, "
          f"{words} English words of narration")
