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
        "完成試飛。G400於2024年首飛。": "完成試飛。 G400於2024年首飛。",
        "第一句。 第二句。  第三句。": "第一句。 第二句。 第三句。",
        "已起飛！下一班呢？仍在準備。": "已起飛！ 下一班呢？ 仍在準備。",
        "他說：「已完成。」下一步試飛。": "他說：「已完成。」 下一步試飛。",
        "真的！？下一句。（附註。）後續。": "真的！？ 下一句。 （附註。） 後續。",
        "第一句。\n第二段。": "第一句。\n第二段。",
        "English sentence. Another with 0.89 and U.S. aviation.": "English sentence. Another with 0.89 and U.S. aviation.",
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

    # Inserting before an entity must not turn escaped text into HTML markup.
    escaped = '<p>第一句。&lt;Next&gt;。&amp;後續。</p>'
    assert compact_html(escaped) == '<p>第一句。 &lt;Next&gt;。 &amp;後續。</p>'
    print("test_text_spacing: OK")


def test_sentence_spacing_across_markup():
    source = '''<p>完成試飛。<strong>G400</strong> 於2024年首飛。 下一句。</p>
<p>他說：「已完成。<em>」</em>後續試飛。</p>
<p>第一句&#12290;<a href="/中文 path/">第二句</a>。 第三句。</p>
<p>第一句。</p><p>第二段。</p>
<p>English sentence. <strong>Another</strong> sentence.</p>
<script>const text = "第一句。第二句。";</script>'''
    result = compact_html(source)
    assert '完成試飛。<strong> G400</strong>於2024年首飛。 下一句。' in result
    assert '已完成。<em>」</em> 後續試飛。' in result
    assert '&#12290;<a href="/中文 path/"> 第二句</a>。 第三句。' in result
    assert '<p>第一句。</p><p>第二段。</p>' in result
    assert '<p>English sentence. <strong>Another</strong> sentence.</p>' in result
    assert '<script>const text = "第一句。第二句。";</script>' in result
    assert compact_html(result) == result


if __name__ == "__main__":
    test_display_spacing()
    test_sentence_spacing_across_markup()
