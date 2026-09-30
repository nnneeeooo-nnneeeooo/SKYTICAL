"""Recover presentation defects without changing source evidence."""
from copy import deepcopy


def normalize_reader_copy(draft, converter):
    """Convert only displayed Chinese; verbatim quotes and entities stay intact."""
    if not isinstance(draft, dict):
        return draft
    result = deepcopy(draft)
    zh = result.get("zh")
    if isinstance(zh, dict):
        for key in ("title", "summary"):
            if isinstance(zh.get(key), str):
                zh[key] = converter.convert(zh[key])
        if isinstance(zh.get("body"), list):
            zh["body"] = [converter.convert(p) if isinstance(p, str) else p
                          for p in zh["body"]]
    flash = result.get("flash")
    if isinstance(flash, dict) and isinstance(flash.get("zh"), str):
        flash["zh"] = converter.convert(flash["zh"])
    incident = result.get("incident")
    if isinstance(incident, dict):
        for key in ("phase", "location", "desc"):
            block = incident.get(key)
            if isinstance(block, dict) and isinstance(block.get("zh"), str):
                block["zh"] = converter.convert(block["zh"])
    return result


def repair_prompt(source_prompt, problem):
    """A retry receives the failed gate, while retaining the original sources."""
    return source_prompt + (
        "\n\nVALIDATION FEEDBACK FROM THE PREVIOUS ATTEMPT:\n"
        + str(problem)[:1200]
        + "\nReturn a complete replacement JSON object satisfying the schema. "
        "Include both summaries. Use publish_brief only for 2-7 paragraphs, "
        "180-320 Chinese content characters and 90-150 English words; "
        "use publish only for 4-7 paragraphs, at least 500 Chinese content "
        "characters and 250 English words. Count before returning. "
        "Use only SOURCE evidence and preserve verbatim source quotes. "
        "Do not add facts, repeat sentences or pad copy to meet a length floor. "
        "If neither format is supported by SOURCE, return reject with the "
        "specific evidence limitation. Do not reject merely because a "
        "previous draft had a format defect."
    )
