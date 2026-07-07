"""
Unit tests for update_gallery.py. Run from the repo root with:

    python3 -m unittest discover -s tests
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import update_gallery as ug  # noqa: E402


class OutStemTests(unittest.TestCase):
    def test_strips_trailing_corrected_suffix(self):
        self.assertEqual(ug.out_stem('IMG_1202_corrected.jpg'), 'IMG_1202')

    def test_leaves_plain_names_alone(self):
        self.assertEqual(ug.out_stem('sunset.png'), 'sunset')

    def test_only_strips_one_trailing_occurrence(self):
        self.assertEqual(ug.out_stem('weird_corrected_corrected.jpg'), 'weird_corrected')


class CaptionParsingTests(unittest.TestCase):
    def test_multiline_description_comments_and_unknown_lines(self):
        text = (
            "# a top-of-file comment\n"
            "some stray line before any section\n"
            "\n"
            "[IMG_1.jpg]\n"
            "title: Sunset\n"
            "meta: 2023 . Oil on canvas\n"
            "# a comment inside the section\n"
            "unknownkey: should be ignored\n"
            "description: Line one\n"
            "  continues here\n"
            "\n"
            "  final line\n"
            "\n"
            "[IMG_2.jpg]\n"
            "title:\n"
            "meta:\n"
            "description:\n"
        )
        result = ug.parse_captions(text)

        self.assertEqual(set(result.keys()), {'IMG_1.jpg', 'IMG_2.jpg'})

        img1 = result['IMG_1.jpg']
        self.assertEqual(img1['title'], 'Sunset')
        self.assertEqual(img1['meta'], '2023 . Oil on canvas')
        self.assertEqual(img1['description'], 'Line one continues here final line')

        img2 = result['IMG_2.jpg']
        self.assertEqual(img2['title'], '')
        self.assertEqual(img2['meta'], '')
        self.assertEqual(img2['description'], '')

    def test_section_with_no_fields_still_present(self):
        result = ug.parse_captions('[empty.jpg]\n')
        self.assertIn('empty.jpg', result)
        self.assertEqual(result['empty.jpg']['title'], '')


class AppendMissingSectionsTests(unittest.TestCase):
    def test_preserves_existing_content_and_adds_stubs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'captions.txt'
            original = (
                "# header comment\n"
                "\n"
                "[A.jpg]\n"
                "title: Foo\n"
                "meta:\n"
                "description: bar\n"
            )
            path.write_text(original, encoding='utf-8')

            ug.append_missing_sections(path, ['B.jpg', 'C.jpg'])

            new_text = path.read_text(encoding='utf-8')
            self.assertTrue(new_text.startswith(original),
                            'existing content must be preserved byte-for-byte')
            self.assertIn('[B.jpg]', new_text)
            self.assertIn('[C.jpg]', new_text)

            parsed = ug.parse_captions(new_text)
            self.assertEqual(parsed['A.jpg']['title'], 'Foo')  # untouched
            self.assertEqual(parsed['B.jpg']['title'], '')
            self.assertEqual(parsed['C.jpg']['title'], '')

    def test_no_missing_names_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'captions.txt'
            original = "[A.jpg]\ntitle: Foo\n"
            path.write_text(original, encoding='utf-8')
            ug.append_missing_sections(path, [])
            self.assertEqual(path.read_text(encoding='utf-8'), original)

    def test_stub_includes_date_line_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'captions.txt'
            path.write_text('', encoding='utf-8')
            ug.append_missing_sections(path, ['A.jpg'])
            text = path.read_text(encoding='utf-8')
            self.assertIn('[A.jpg]\ntitle:\nmeta:\ndate:\ndescription:\n', text)


class DateParsingTests(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(ug.parse_date('', 'sec'), '')
        self.assertEqual(ug.parse_date('   ', 'sec'), '')

    def test_year_only(self):
        self.assertEqual(ug.parse_date('2023', 'sec'), '2023')
        self.assertEqual(ug.parse_date('2023.', 'sec'), '2023')

    def test_iso_year_month(self):
        self.assertEqual(ug.parse_date('2023-05', 'sec'), '2023-05')

    def test_month_slash_year(self):
        self.assertEqual(ug.parse_date('5/2023', 'sec'), '2023-05')
        self.assertEqual(ug.parse_date('05/2023', 'sec'), '2023-05')

    def test_month_dot_year(self):
        self.assertEqual(ug.parse_date('5.2023', 'sec'), '2023-05')

    def test_day_month_year_dot(self):
        self.assertEqual(ug.parse_date('12.5.2023', 'sec'), '2023-05-12')
        self.assertEqual(ug.parse_date('12. 5. 2023', 'sec'), '2023-05-12')

    def test_iso_full_date(self):
        self.assertEqual(ug.parse_date('2023-05-12', 'sec'), '2023-05-12')

    def test_invalid_month_range_warns_and_returns_empty(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = ug.parse_date('13/2023', 'MySection')
        self.assertEqual(result, '')
        self.assertIn('MySection', buf.getvalue())

    def test_invalid_day_range_warns_and_returns_empty(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = ug.parse_date('31.2.2023', 'MySection')
        self.assertEqual(result, '')
        self.assertIn('MySection', buf.getvalue())

    def test_unparseable_garbage_warns_and_returns_empty(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = ug.parse_date('not a date', 'MySection')
        self.assertEqual(result, '')
        self.assertIn('MySection', buf.getvalue())


class CaptionsMigrationTests(unittest.TestCase):
    """The new parse_captions/CAPTIONS_HEADER should carry old-format
    (no date: field) captions.txt content forward without losing data."""

    def test_old_format_values_carry_over_with_empty_date(self):
        old_text = (
            "# Popisky k obrazum pro galerii\n"
            "\n"
            "[IMG_1.jpg]\n"
            "title: Sunset\n"
            "meta: 2023, oil on canvas\n"
            "description: A nice sunset.\n"
            "\n"
            "[IMG_2.jpg]\n"
            "title:\n"
            "meta:\n"
            "description:\n"
        )
        parsed = ug.parse_captions(old_text)
        self.assertEqual(parsed['IMG_1.jpg']['title'], 'Sunset')
        self.assertEqual(parsed['IMG_1.jpg']['meta'], '2023, oil on canvas')
        self.assertEqual(parsed['IMG_1.jpg']['date'], '')
        self.assertEqual(parsed['IMG_1.jpg']['description'], 'A nice sunset.')
        self.assertEqual(parsed['IMG_2.jpg']['title'], '')
        self.assertEqual(parsed['IMG_2.jpg']['date'], '')

    def test_new_header_is_english_only(self):
        self.assertNotIn('Popisky', ug.CAPTIONS_HEADER)
        self.assertIn('date:', ug.CAPTIONS_HEADER)


class PipelineIntegrationTests(unittest.TestCase):
    """End-to-end tests of run() against tiny synthetic images."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source_dir = Path(self.tmp.name) / 'source'
        self.out_dir = Path(self.tmp.name) / 'out'
        self.source_dir.mkdir()
        self._make_source_images()

    def tearDown(self):
        self.tmp.cleanup()

    def _make_source_images(self):
        # Deliberately named so lexicographic order would be wrong
        # (img10 before img2) but natural order is right.
        Image.new('RGB', (100, 60), (200, 50, 50)).save(
            self.source_dir / 'img1_corrected.jpg', quality=90)
        Image.new('RGB', (120, 80), (50, 200, 50)).save(
            self.source_dir / 'img2_corrected.jpg', quality=90)

        rgba = Image.new('RGBA', (90, 70), (0, 0, 255, 255))
        for x in range(10):
            for y in range(10):
                rgba.putpixel((x, y), (0, 0, 0, 0))  # transparent corner
        rgba.save(self.source_dir / 'img10_corrected.png')

    def _run(self, force=False):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ug.run(self.source_dir, self.out_dir, force)
        return buf.getvalue()

    def test_manifest_order_and_dimensions(self):
        self._run()
        manifest = json.loads((self.out_dir / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(
            [e['file'] for e in manifest],
            ['web/img1.jpg', 'web/img2.jpg', 'web/img10.jpg'],
        )
        self.assertEqual(
            [e['thumb'] for e in manifest],
            ['thumbs/img1.jpg', 'thumbs/img2.jpg', 'thumbs/img10.jpg'],
        )
        for entry in manifest:
            self.assertEqual(entry['title'], '')
            self.assertEqual(entry['meta'], '')
            self.assertEqual(entry['description'], '')
        self.assertEqual((manifest[0]['width'], manifest[0]['height']), (100, 60))

    def test_manifest_follows_captions_file_order(self):
        # First run creates stub sections in natural order.
        self._run()
        captions_path = self.out_dir / 'captions.txt'

        # Manager reorders the gallery by moving whole sections: put img10
        # first, then img1, then img2 - a deliberately non-natural order.
        reordered = ''.join(
            f'[{name}]\ntitle:\nmeta:\ndate:\ndescription:\n\n'
            for name in ('img10_corrected.png', 'img1_corrected.jpg', 'img2_corrected.jpg')
        )
        captions_path.write_text(reordered, encoding='utf-8')

        self._run()
        manifest = json.loads((self.out_dir / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(
            [e['file'] for e in manifest],
            ['web/img10.jpg', 'web/img1.jpg', 'web/img2.jpg'],
        )

    def test_new_images_append_after_existing_caption_order(self):
        # A captions.txt that only mentions img2 (in the "first" slot); img1
        # and img10 have no section yet and must be appended after it.
        captions_path = self.out_dir / 'captions.txt'
        self.out_dir.mkdir(parents=True, exist_ok=True)
        captions_path.write_text(
            '[img2_corrected.jpg]\ntitle: Two\nmeta:\ndate:\ndescription:\n',
            encoding='utf-8',
        )
        self._run()
        manifest = json.loads(captions_path.with_name('manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest[0]['file'], 'web/img2.jpg')
        # the two newly stubbed images follow, in natural order
        self.assertEqual(
            [e['file'] for e in manifest[1:]],
            ['web/img1.jpg', 'web/img10.jpg'],
        )

    def test_rgba_source_becomes_plain_rgb_jpeg(self):
        self._run()
        web_path = self.out_dir / 'web' / 'img10.jpg'
        with Image.open(web_path) as img:
            self.assertEqual(img.mode, 'RGB')
            r, g, b = img.getpixel((2, 2))
            # transparent corner should have been composited onto white
            self.assertGreater(r, 200)
            self.assertGreater(g, 200)
            self.assertGreater(b, 200)

    def test_captions_stub_created_for_every_source_image(self):
        self._run()
        text = (self.out_dir / 'captions.txt').read_text(encoding='utf-8')
        for name in ('img1_corrected.jpg', 'img2_corrected.jpg', 'img10_corrected.png'):
            self.assertIn(f'[{name}]', text)

    def test_incremental_skip_then_force_reprocesses(self):
        first = self._run()
        self.assertIn('processed: 3, skipped (up to date): 0', first)

        second = self._run()
        self.assertIn('processed: 0, skipped (up to date): 3', second)

        third = self._run(force=True)
        self.assertIn('processed: 3, skipped (up to date): 0', third)

    def test_orphan_cleanup_removes_stale_derivatives(self):
        self._run()
        (self.source_dir / 'img2_corrected.jpg').unlink()
        self._run()

        self.assertFalse((self.out_dir / 'web' / 'img2.jpg').exists())
        self.assertFalse((self.out_dir / 'thumbs' / 'img2.jpg').exists())
        self.assertFalse((self.out_dir / 'hires' / 'img2.jpg').exists())

        manifest = json.loads((self.out_dir / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest), 2)
        self.assertNotIn('web/img2.jpg', [e['file'] for e in manifest])

    def test_hires_derivative_produced_and_in_manifest(self):
        self._run()
        for stem in ('img1', 'img2', 'img10'):
            hires_path = self.out_dir / 'hires' / f'{stem}.jpg'
            self.assertTrue(hires_path.exists(), f'{hires_path} should exist')
            with Image.open(hires_path) as img:
                self.assertEqual(img.mode, 'RGB')

        manifest = json.loads((self.out_dir / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual([e['hires'] for e in manifest],
                          ['hires/img1.jpg', 'hires/img2.jpg', 'hires/img10.jpg'])
        for entry in manifest:
            self.assertEqual(entry['date'], '')

    def test_small_sources_never_downscaled_dont_crash_the_blur_step(self):
        # All synthetic sources here are smaller than every derivative's
        # max edge, so fit() takes the no-downscale branch and must not
        # attempt to apply a blur (or crash trying to).
        output = self._run()
        self.assertNotIn('Traceback', output)
        for tier, stem in (('web', 'img1'), ('thumbs', 'img1'), ('hires', 'img1')):
            with Image.open(self.out_dir / tier / f'{stem}.jpg') as img:
                self.assertEqual(img.size, (100, 60))


class DeskewStageTests(unittest.TestCase):
    """Tests the deskew stage's counterpart-detection / ignore-list logic
    using a stubbed deskew module - never invokes real GrabCut/cv2."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self.tmp.name) / 'raw_photos'
        self.cropped_dir = Path(self.tmp.name) / 'cropped'
        self.raw_dir.mkdir()
        self.cropped_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, directory, name):
        (directory / name).write_bytes(b'')

    class _StubDeskew:
        def __init__(self, outcomes=None):
            self.calls = []
            self.outcomes = outcomes or {}

        def process(self, path, outdir, debugdir=None):
            name = Path(path).name
            self.calls.append(name)
            if name in self.outcomes:
                return self.outcomes[name]
            # default: succeed
            return str(Path(outdir) / (Path(path).stem + '_corrected.jpg'))

    def test_skip_true_does_nothing(self):
        stub = self._StubDeskew()
        ug.run_deskew_stage(self.raw_dir, self.cropped_dir, True, deskew_module=stub)
        self.assertEqual(stub.calls, [])

    def test_missing_raw_dir_prints_note_and_returns(self):
        missing_dir = Path(self.tmp.name) / 'does_not_exist'
        stub = self._StubDeskew()
        buf = io.StringIO()
        with redirect_stdout(buf):
            ug.run_deskew_stage(missing_dir, self.cropped_dir, False, deskew_module=stub)
        self.assertEqual(stub.calls, [])
        self.assertIn('not found', buf.getvalue())

    def test_already_corrected_counterpart_is_skipped_silently(self):
        self._touch(self.raw_dir, 'IMG_1.JPG')
        self._touch(self.cropped_dir, 'IMG_1_corrected.jpg')
        stub = self._StubDeskew()
        ug.run_deskew_stage(self.raw_dir, self.cropped_dir, False, deskew_module=stub)
        self.assertEqual(stub.calls, [])  # never invoked for an already-corrected photo

    def test_png_counterpart_also_counts_as_already_corrected(self):
        self._touch(self.raw_dir, 'IMG_2.JPG')
        self._touch(self.cropped_dir, 'IMG_2_corrected.png')
        stub = self._StubDeskew()
        ug.run_deskew_stage(self.raw_dir, self.cropped_dir, False, deskew_module=stub)
        self.assertEqual(stub.calls, [])

    def test_ignore_list_skips_listed_files_case_insensitively(self):
        self._touch(self.raw_dir, 'IMG_3.JPG')
        (self.raw_dir.parent / 'raw_ignore.txt').write_text(
            '# comment\nimg_3.jpg\n', encoding='utf-8')
        stub = self._StubDeskew()
        ug.run_deskew_stage(self.raw_dir, self.cropped_dir, False, deskew_module=stub)
        self.assertEqual(stub.calls, [])

    def test_new_photo_without_counterpart_gets_deskewed(self):
        self._touch(self.raw_dir, 'IMG_4.JPG')
        stub = self._StubDeskew()
        ug.run_deskew_stage(self.raw_dir, self.cropped_dir, False, deskew_module=stub)
        self.assertEqual(stub.calls, ['IMG_4.JPG'])

    def test_failed_deskew_is_reported_with_guidance(self):
        self._touch(self.raw_dir, 'IMG_5.JPG')
        stub = self._StubDeskew(outcomes={'IMG_5.JPG': None})
        buf = io.StringIO()
        with redirect_stdout(buf):
            ug.run_deskew_stage(self.raw_dir, self.cropped_dir, False, deskew_module=stub)
        output = buf.getvalue()
        self.assertIn('failed: 1', output)
        self.assertIn('IMG_5.JPG', output)
        self.assertIn('manual_corner_crop.html', output)
        self.assertIn('raw_ignore.txt', output)


if __name__ == '__main__':
    unittest.main()
