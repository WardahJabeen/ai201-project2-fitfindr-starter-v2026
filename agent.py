"""
The FitFindr planning loop.

This is the file that makes FitFindr an agent rather than a script. It decides
which tool to run next based on what the last one returned.

If your loop calls all three tools no matter what comes back, you have a list
of function calls. A loop looks at the last result before it picks the next
step. **That branch is the graded part of this unit.**

Build and test your three tools in `tools.py` first. Then come here.

    python agent.py          runs both example paths below
"""

import re

import config
import trace
from tools import search_listings, suggest_outfit, create_fit_card
from generate import ModelUnavailable


# ── session state ─────────────────────────────────────────────────────────────

def new_session(query: str, wardrobe: dict) -> dict:
    """
    A fresh session for one user interaction.

    The session is the single source of truth for a run. Every tool result goes
    in here, and the next tool reads it back out.

    You could pass values straight from one call to the next. It would work,
    and you would not be able to test it — you can't print a variable you have
    already overwritten. Going through the session is what makes the state
    visible, and unit 4 has you write a criterion about exactly that.

    Add fields if you need them.
    """
    return {
        "query": query,              # what the user typed
        "parsed": {},                # description / size / max_price you pulled out of it
        "search_results": [],        # everything search_listings returned
        "selected_item": None,       # the one you chose — goes into suggest_outfit
        "wardrobe": wardrobe,        # the user's wardrobe
        "outfit_suggestion": None,   # what suggest_outfit returned
        "fit_card": None,            # what create_fit_card returned
        "error": None,               # set when the run ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Run the loop once and return the finished session.

    Args:
        query:    what the user asked for, in plain language
                  (e.g. "vintage graphic tee under $30, size M").
        wardrobe: a wardrobe dict — get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py.

    Returns:
        The session dict. **Check session["error"] first** — if it isn't None,
        the run ended early and the later fields will still be None.

    ─────────────────────────────────────────────────────────────────────────
    TODO — build this, following the branch rule you wrote in Milestone 2.

      1. Start a session with new_session().

      2. Count the times round the loop, and call trace.check_iterations(count)
         on each one before you go again. It raises when the count passes
         MAX_ITERATIONS in config.py — see trace.py.

      3. Parse the query into a description, a size, and a max_price. Regex,
         string splitting, or asking the model are all fine — say which you
         chose in your README. Put the result in session["parsed"].

      4. Call search_listings() with what you parsed.
         Put the results in session["search_results"].

         ⚠️ THIS IS THE BRANCH. If nothing came back:
              - put a message in session["error"] saying what the user could
                change — "No results" is not that message
              - return the session
              - do NOT call suggest_outfit with nothing

      5. Choose an item — the first result is fine. Put it in
         session["selected_item"].

      6. Call suggest_outfit() with the selected item and the wardrobe.
         Put the result in session["outfit_suggestion"].

      7. Call create_fit_card() with the outfit and the item.
         Put the result in session["fit_card"].

      8. Return the session.

    ─────────────────────────────────────────────────────────────────────────
    IN UNIT 4 you come back and add two things:

      • Trace calls. One per step. `trace.step("search_listings", inputs=...,
        returned=...)` — see trace.py. Your README needs the output.

      • A handler for ModelUnavailable, so a bad key produces a message rather
        than a stack trace. The import is already at the top of this file.
    """
    session = new_session(query, wardrobe)

    # Each pass runs one step, then looks at what that step produced to decide
    # the next one. "done" ends the loop.
    next_step = "parse"
    count = 0

    while next_step != "done":
        count += 1
        trace.check_iterations(count)

        if next_step == "parse":
            session["parsed"] = parse_query(query)
            next_step = "search"

        elif next_step == "search":
            parsed = session["parsed"]
            results = search_listings(
                parsed["description"],
                size=parsed["size"],
                max_price=parsed["max_price"],
            )
            session["search_results"] = results or []

            # THE BRANCH: nothing matched, so stop before suggest_outfit.
            if not session["search_results"]:
                session["error"] = _no_results_message(parsed)
                next_step = "done"
            else:
                next_step = "select"

        elif next_step == "select":
            session["selected_item"] = session["search_results"][0]
            next_step = "outfit"

        elif next_step == "outfit":
            session["outfit_suggestion"] = suggest_outfit(
                session["selected_item"], session["wardrobe"]
            )
            next_step = "fit_card"

        elif next_step == "fit_card":
            session["fit_card"] = create_fit_card(
                session["outfit_suggestion"], session["selected_item"]
            )
            next_step = "done"

    return session


# ── query parsing ─────────────────────────────────────────────────────────────

_SIZE_WORDS = {
    "extra small": "XS", "small": "S", "medium": "M",
    "large": "L", "extra large": "XL",
}

# "size M", "size XXS", "size US 9", "size W30", "size 8.5", "size one size"
_SIZE_RE = re.compile(
    r"\bsize\s+("
    r"one size"
    r"|us\s?\d+(?:\.\d+)?"
    r"|w\d+(?:\s?l\d+)?"
    r"|x{0,3}[sl]|m|xl|xxl"
    r"|extra small|extra large|small|medium|large"
    r"|\d+(?:\.\d+)?"
    r")\b",
    re.IGNORECASE,
)

# "under $30", "below 25", "less than $40", "max $50", "up to $20", "$30 or less"
_PRICE_RE = re.compile(
    r"(?:under|below|less than|max(?:imum)?|up to|at most|<)\s*\$?\s*(\d+(?:\.\d+)?)"
    r"|\$\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

_FILLER_RE = re.compile(
    r"\b(?:i'?m|i am|looking for|searching for|search for|find me|find|"
    r"i want|i need|want|need|show me|please|a|an|some|any|in)\b",
    re.IGNORECASE,
)


def parse_query(query: str) -> dict:
    """
    Pull a description, size, and max_price out of a plain-language query,
    using regex. Anything not found is None; the description is whatever is
    left once the size, price, and filler words are removed.
    """
    text = query

    size = None
    m = _SIZE_RE.search(text)
    if m:
        raw = m.group(1).strip()
        size = _SIZE_WORDS.get(raw.lower(), raw.upper())
        text = text[:m.start()] + " " + text[m.end():]

    max_price = None
    m = _PRICE_RE.search(text)
    if m:
        max_price = float(m.group(1) or m.group(2))
        text = text[:m.start()] + " " + text[m.end():]

    text = _FILLER_RE.sub(" ", text)
    text = re.sub(r"\s*,\s*", " ", text)
    description = " ".join(text.split()).strip(" .,!?")

    return {"description": description, "size": size, "max_price": max_price}


def _no_results_message(parsed: dict) -> str:
    """Say what came up empty and what the user could loosen."""
    what = f"'{parsed['description']}'" if parsed["description"] else "that search"
    filters = []
    if parsed["size"]:
        filters.append(f"size {parsed['size']}")
    if parsed["max_price"] is not None:
        filters.append(f"under ${parsed['max_price']:.0f}")

    msg = f"No listings matched {what}"
    if filters:
        msg += " (" + ", ".join(filters) + ")"
    msg += ". Try "
    suggestions = []
    if parsed["max_price"] is not None:
        suggestions.append("raising your budget")
    if parsed["size"]:
        suggestions.append("dropping the size filter")
    suggestions.append("using broader keywords (e.g. 'jacket' instead of a brand or exact style)")
    if len(suggestions) > 1:
        msg += ", ".join(suggestions[:-1]) + ", or " + suggestions[-1]
    else:
        msg += suggestions[0]
    return msg + "."


# ── running it directly ───────────────────────────────────────────────────────

def _show(session: dict) -> None:
    if session["error"]:
        print(f"  stopped: {session['error']}")
        print(f"  fit_card is {session['fit_card']!r} — it should still be None here")
        return

    item = session["selected_item"] or {}
    print(f"  found:    {item.get('title')} — ${item.get('price')} on {item.get('platform')}")
    print(f"  outfit:   {session['outfit_suggestion']}")
    print(f"  fit card: {session['fit_card']}")


if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe

    print("=== A query the data can match ===")
    _show(run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    ))

    print("\n=== A query it can't ===")
    _show(run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    ))

    print(
        "\nThe second one should stop before the fit card. If both paths look "
        "the same,\nthe branch isn't doing anything yet."
    )
