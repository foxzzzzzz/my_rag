import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.demo_extract import extract_html, probe_media

class ExtractTests(unittest.TestCase):
    def test_html(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'a.html'
            p.write_text('<title>T</title><nav>bad</nav><main><h1>Hello</h1><script>evil</script><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table><pre><code>  x\n y</code></pre><svg><path d="M0 0L1 1"/></svg></main>', encoding='utf-8')
            r = extract_html(p, Path(d)/'assets')
            self.assertEqual(r['title'], 'T')
            self.assertIn('| A | B |', r['markdown'])
            self.assertIn('  x\n y', r['markdown'])
            self.assertNotIn('evil', r['markdown'])
            self.assertEqual(r['markdown'].count('```'), 2)
            self.assertIn('M0 0L1 1', r['svg_context'])
            self.assertEqual(len(r['svg_files']), 1)
    def test_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.html'; p.write_text('<body><nav>bad</nav><p>good</p></body>')
            r=extract_html(p,Path(d)/'a'); self.assertIn('good',r['markdown']); self.assertNotIn('bad',r['markdown'])
    @patch('tools.demo_extract.subprocess.run')
    def test_probe(self, run):
        run.return_value.stderr='Duration: 00:01:02.50, start: 0\nStream #0:0: Video: h264, yuv420p, 1920x1080\nStream #0:1: Audio: aac'
        r=probe_media('x','ffmpeg',20)
        self.assertEqual(r,dict(duration_seconds=62.5,width=1920,height=1080,has_audio=True))
        self.assertFalse(run.call_args.kwargs['shell'])

class SvgFidelityTests(unittest.TestCase):
    def test_svg_source_and_code_entities(self):
        with tempfile.TemporaryDirectory() as d:
            source='<svg viewBox="0 0 1 1"><TEXT  x="1">A &amp; B</TEXT  ></svg >'
            p=Path(d)/'source.html'; p.write_text('<main><pre><code>&lt;a&gt; &amp;</code></pre>'+source+'</main>',encoding='utf-8')
            result=extract_html(p,Path(d)/'assets')
            self.assertEqual(Path(result['svg_files'][0]).read_text(encoding='utf-8'),source)
            self.assertIn('<a> &',result['markdown'])
