import threading
from http.server import ThreadingHTTPServer

import pytest
from PIL import Image

import ptouch_bridge
from ptouch import (HTTPTransport, JobOptions, PrinterError, PrinterStatus, TransportError,
                    build_feed_job, build_job, build_jobs, render_image, render_qr, render_text,
                    tape_pins)
from ptouch.protocol import (MODEL_P300BT, STATUS_COMPLETED, STATUS_ERROR, image_to_lines, packbits,
                             split_status_packets, unpackbits)
from ptouch.transport import Transport


def status_bytes(width=12, media=0x01, err1=0, err2=0, stype=0x00, phase=0x00, colour=0x01, text=0x08,
                 model=0x00):
    b = bytearray(32)
    b[0], b[1], b[2], b[3], b[4] = 0x80, 0x20, 0x42, 0x30, model
    b[8], b[9], b[10], b[11], b[18], b[19], b[24], b[25] = err1, err2, width, media, stype, phase, colour, text
    return bytes(b)


def test_packbits_roundtrip():
    import random
    rnd = random.Random(1)
    for _ in range(300):
        data = bytes(rnd.choice([0, 0, 0xFF, rnd.randrange(256)]) for _ in range(16))
        assert unpackbits(packbits(data)) == data
    assert packbits(b"\x00" * 16) == bytes([257 - 16, 0])
    assert unpackbits(packbits(bytes(range(200)))) == bytes(range(200))


def test_status_parse():
    st = PrinterStatus.parse(status_bytes(width=24, colour=0x01))
    assert st.has_tape and st.media_width == 24 and st.state == "idle"
    assert st.tape_colour_name == "white" and st.media_type_name == "laminated"
    err = PrinterStatus.parse(status_bytes(err1=0b1, err2=0b10000))
    assert err.errors == ["no_media", "cover_open"] and err.state == "error"
    with pytest.raises(Exception):
        PrinterStatus.parse(b"\x00" * 32)


def test_model_overrides_geometry(monkeypatch):
    from ptouch import protocol
    monkeypatch.setitem(protocol.MODEL_TAPE_GEOMETRY, 0x99, {12: (64, 32)})
    assert PrinterStatus.parse(status_bytes(model=0x99)).model == 0x99
    assert tape_pins(12, 0x99) == 64 and tape_pins(12) == 70 and tape_pins(9, 0x99) == 50
    lines = image_to_lines(Image.new("1", (1, 64), 0), 12, model=0x99)
    assert int.from_bytes(lines[0], "big") == ((1 << 64) - 1) << 32      # pins 32..95
    assert render_text("x", 12, model=0x99).height == 64


def test_status_model():
    st = PrinterStatus.parse(status_bytes(model=MODEL_P300BT))
    assert st.model == MODEL_P300BT and st.model_name == "PT-P300BT"
    assert PrinterStatus.parse(status_bytes()).model_name is None


def test_status_resync():
    buf = bytearray(b"\x01\x02" + status_bytes() + status_bytes(width=6)[:10])
    pkts = split_status_packets(buf)
    assert len(pkts) == 1 and pkts[0].media_width == 12
    buf += status_bytes(width=6)[10:]
    assert split_status_packets(buf)[0].media_width == 6


@pytest.mark.parametrize("mm", [4, 6, 9, 12, 18, 24])
def test_lines_geometry(mm):
    pins = tape_pins(mm)
    img = Image.new("1", (10, pins), 1)
    img.putpixel((3, 0), 0)            # top pixel of column 3
    img.putpixel((3, pins - 1), 0)     # bottom pixel of column 3
    lines = image_to_lines(img, mm)
    assert len(lines) == 10 and all(len(l) == 16 for l in lines)
    assert not any(lines[0]) and any(lines[3])
    bits = int.from_bytes(lines[3], "big")
    left = (128 - pins) // 2 if mm != 9 else 39
    assert bits >> (127 - left) & 1 and bits >> (127 - (left + pins - 1)) & 1
    assert bin(bits).count("1") == 2
    flipped = image_to_lines(img, mm, "flip_feed")
    assert any(flipped[6]) and not any(flipped[3])


def test_p300bt_geometry():
    assert tape_pins(12, MODEL_P300BT) == 64 and tape_pins(12) == 70
    for mm in (4, 6, 9):
        assert tape_pins(mm, MODEL_P300BT) == tape_pins(mm)
    lines = image_to_lines(Image.new("1", (1, 64), 0), 12, model=MODEL_P300BT)
    assert int.from_bytes(lines[0], "big") == ((1 << 64) - 1) << 32      # pins 32..95
    with pytest.raises(Exception):
        image_to_lines(Image.new("1", (1, 70), 0), 12, model=MODEL_P300BT)


def test_p300bt_never_cuts():
    job = build_job([Image.new("1", (20, 64), 0)], JobOptions(tape_mm=12, model=MODEL_P300BT))
    assert b"\x1biM\x00" in job and b"\x1biM\x40" not in job


def test_cut_mark_only_without_cutter():
    img = Image.new("1", (20, 64), 0)
    assert b"\x1biM\x40" in build_job([img], JobOptions(tape_mm=12, model=MODEL_P300BT, cut_mark=True))
    p710 = Image.new("1", (20, 70), 0)                     # with a cutter, auto_cut alone decides
    assert b"\x1biM\x00" in build_job([p710], JobOptions(tape_mm=12, auto_cut=False, cut_mark=True))


def test_chain_printing():
    img = Image.new("1", (20, 70), 0)
    assert b"\x1biK\x08" in build_job([img], JobOptions(tape_mm=12))
    assert b"\x1biK\x00" in build_job([img], JobOptions(tape_mm=12, chain=True))


def test_cut_marks_split_labels_into_jobs():
    imgs = [Image.new("1", (20, 64), 0)] * 3
    assert len(build_jobs(imgs, JobOptions(tape_mm=12, model=MODEL_P300BT))) == 1
    jobs = build_jobs(imgs, JobOptions(tape_mm=12, model=MODEL_P300BT, cut_mark=True, chain=True))
    assert len(jobs) == 3 and all(b"\x1biM\x40" in j and b"\x1biK\x00" in j for j in jobs)


def test_feed_job():
    job = build_feed_job(JobOptions(tape_mm=12, model=MODEL_P300BT, chain=True, cut_mark=True))
    i = job.index(b"\x1biz")
    assert int.from_bytes(job[i + 7:i + 11], "little") == 1          # one raster line ...
    assert job.endswith(b"Z\x1a")                                    # ... blank, then print: never a bare 0x1A
    assert b"\x1biK\x08" in job and b"\x1biM\x00" in job and b"\x1bid\x00\x00" in job


def test_wrong_height_rejected():
    with pytest.raises(Exception):
        image_to_lines(Image.new("1", (5, 10), 1), 12)


def test_build_job_structure():
    img = Image.new("1", (20, 70), 0)
    job = build_job([img], JobOptions(tape_mm=12))
    assert job.startswith(b"\x00" * 100 + b"\x1b@" + b"\x1bia\x01")
    assert job.count(b"\x1biz") == 1 and job.endswith(b"\x1a")
    i = job.index(b"\x1biz")
    n1, media, width, length = job[i + 3:i + 7]
    assert (n1, media, width, length) == (0x86, 0x01, 12, 0)
    assert int.from_bytes(job[i + 7:i + 11], "little") == 20 and job[i + 11] == 0
    assert b"\x1biM\x40" in job and b"\x1biK\x08" in job and b"\x1bid\x0e\x00" in job and b"M\x02" in job
    assert b"\x1biM\x00" in build_job([img], JobOptions(tape_mm=12, auto_cut=False))
    with pytest.raises(Exception):
        build_job([img], JobOptions(tape_mm=12, media_type=0xFF))


def test_blank_lines_use_Z():
    job = build_job([Image.new("1", (5, 70), 1)], JobOptions(tape_mm=12))
    assert job.count(b"Z") >= 5


@pytest.mark.parametrize("model", [None, MODEL_P300BT])
def test_render_heights(model):
    for mm in (6, 9, 12, 18, 24):
        pins = tape_pins(mm, model)
        assert render_text("Hello\nWorld", mm, model=model).height == pins
        assert render_text("x", mm, font_size=20, model=model).height == pins
        assert render_qr("https://example.com", mm, model=model).height == pins if mm >= 12 else True
        assert render_image(Image.new("RGB", (300, 100), "red"), mm, model=model).height == pins


def test_text_has_ink():
    img = render_text("ABC", 12)
    assert img.getextrema() == (0, 1)


# ---- bridge round trip with a fake printer -------------------------------
class FakePrinter(Transport):
    def __init__(self):
        self.jobs, self.fail = [], None

    def get_status(self):
        return PrinterStatus.parse(status_bytes(width=12))

    def print_job(self, data, pages=1):
        if self.fail:
            raise PrinterError(self.fail)
        self.jobs.append((data, pages))


@pytest.fixture
def bridge():
    fake = FakePrinter()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ptouch_bridge.make_handler(fake, "s3cret"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield fake, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_bridge_status_and_print(bridge):
    fake, url = bridge
    t = HTTPTransport(url, "s3cret")
    assert t.get_status().media_width == 12
    t.print_job(b"jobdata", pages=3)
    assert fake.jobs == [(b"jobdata", 3)]


def test_bridge_auth_and_errors(bridge):
    fake, url = bridge
    with pytest.raises(TransportError):
        HTTPTransport(url, "wrong").get_status()
    fake.fail = ["cover_open", "no_media"]
    with pytest.raises(PrinterError) as e:
        HTTPTransport(url, "s3cret").print_job(b"x")
    assert e.value.errors == ["cover_open", "no_media"]
    with pytest.raises(TransportError):
        HTTPTransport("http://127.0.0.1:1", None).get_status()


def test_strip_is_one_page_with_gaps():
    from ptouch.protocol import compose_strip
    imgs = [Image.new("1", (w, 70), 0) for w in (20, 30, 10)]
    strip = compose_strip(imgs, 14)
    assert strip.size == (20 + 30 + 10 + 28, 70)
    job = build_job(imgs, JobOptions(tape_mm=12))
    assert job.count(b"\x1biz") == 1 and job.count(b"\x1biM") == 1 and job.endswith(b"\x1a")
    i = job.index(b"\x1biz")
    assert int.from_bytes(job[i + 7:i + 11], "little") == strip.width
    # a gap column is blank, so there is at least one Z line
    assert b"Z" in job


def test_build_jobs_splitting():
    from ptouch import build_jobs
    from ptouch.protocol import MAX_STRIP_DOTS
    imgs = [Image.new("1", (20, 70), 0)] * 3
    assert len(build_jobs(imgs, JobOptions(tape_mm=12))) == 1
    assert len(build_jobs(imgs, JobOptions(tape_mm=12, cut_each=True))) == 3
    big = [Image.new("1", (MAX_STRIP_DOTS - 100, 70), 0)] * 2
    assert len(build_jobs(big, JobOptions(tape_mm=12))) == 2
    with pytest.raises(Exception):
        build_job([Image.new("1", (MAX_STRIP_DOTS + 1, 70), 0)], JobOptions(tape_mm=12))
