"""Spacing at the HTML display boundary, including inline markup."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from text_spacing import compact_html, compact_text


def test_display_spacing():
    cases = {
        "中 文 航 空": "中文航空",
        "SKYTICAL 是 AI 航空新聞": "SKYTICAL是AI航空新聞",
        "New York 的 Boeing 787 航機": "New York的Boeing 787航機",
        "Latest News and Air France": "Latest News and Air France",
        "中文 123 航班（ TPE ）": "中文123航班（TPE）",
        "中文\u00a0English": "中文\u00a0English",
        "𠀀 English": "𠀀English",
    }
    for original, expected in cases.items():
        assert compact_text(original) == expected, (original, compact_text(original))
    original = '''<!DOCTYPE html>
<meta name="description" content="SKYTICAL 的 AI 新聞">
<p title='中文 &amp; English'>中文 <strong>AI</strong> 航空 <a href="/中文 path/">New York</a> 新聞</p>
<p>English </p><p>中文</p><p>中文&#32;<b>AI</b> 航空&nbsp;English &amp; More</p>
<pre>中文 AI</pre><code>中文 AI</code><textarea>中文 AI</textarea>
<script>const text = "中文 AI";</script><style>/* 中文 AI */</style>
<!-- 中文 AI --><input placeholder="搜尋 SKYTICAL 新聞" value="中文 AI">
'''
    result = compact_html(original)
    assert '<p title=\'中文&amp; English\'>中文<strong>AI</strong>航空<a href="/中文 path/">New York</a>新聞</p>' in result
    assert '<p>English </p><p>中文</p>' in result
    assert '<p>中文<b>AI</b>航空&nbsp;English &amp; More</p>' in result
    assert 'content="SKYTICAL的AI新聞"' in result
    assert 'placeholder="搜尋SKYTICAL新聞" value="中文 AI"' in result
    for preserved in ('<pre>中文 AI</pre>', '<code>中文 AI</code>',
                      '<textarea>中文 AI</textarea>',
                      '<script>const text = "中文 AI";</script>',
                      '<style>/* 中文 AI */</style>', '<!-- 中文 AI -->'):
        assert preserved in result
    assert compact_html(result) == result
    print("test_text_spacing: OK")


if __name__ == "__main__":
    test_display_spacing()
