from unittest.mock import MagicMock

from app.services import video_thumbnail


def _probe_result(stdout: str):
    result = MagicMock()
    result.stdout = stdout
    return result


def test_prepend_thumbnail_frame_builds_segment_and_concat_with_audio(tmp_path, monkeypatch):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake video")
    image_path = tmp_path / "thumb.png"
    from PIL import Image

    Image.new("RGB", (1080, 1920), (255, 0, 0)).save(image_path)
    out_path = tmp_path / "out.mp4"

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffprobe":
            if "v:0" in cmd:
                return _probe_result("1080\n1920\n30/1\n")
            return _probe_result("44100\n2\n")
        return MagicMock()

    monkeypatch.setattr(video_thumbnail.subprocess, "run", fake_run)

    video_thumbnail.prepend_thumbnail_frame(str(video_path), str(image_path), out_path)

    assert calls[0][:2] == ["ffprobe", "-v"]
    assert "v:0" in calls[0]
    assert "a:0" in calls[1]

    assert len(calls) == 3
    ffmpeg_cmd = calls[2]
    assert ffmpeg_cmd[0] == "ffmpeg"
    assert "-loop" in ffmpeg_cmd and "1" in ffmpeg_cmd
    # 1/30s frame duration
    t_index = ffmpeg_cmd.index("-t")
    assert ffmpeg_cmd[t_index + 1] == "0.033"
    assert any(arg.startswith("anullsrc=r=44100:cl=stereo") for arg in ffmpeg_cmd)
    assert "-c:a" in ffmpeg_cmd and "aac" in ffmpeg_cmd
    filter_complex = ffmpeg_cmd[ffmpeg_cmd.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=1" in filter_complex
    assert "-map" in ffmpeg_cmd and "[outv]" in ffmpeg_cmd and "[outa]" in ffmpeg_cmd
    assert str(out_path) == ffmpeg_cmd[-1]


def test_prepend_thumbnail_frame_no_audio_uses_an_flag(tmp_path, monkeypatch):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake video")
    image_path = tmp_path / "thumb.png"
    from PIL import Image

    Image.new("RGB", (400, 300), (0, 255, 0)).save(image_path)
    out_path = tmp_path / "out.mp4"

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffprobe":
            if "v:0" in cmd:
                return _probe_result("400\n300\n25/1\n")
            return _probe_result("")  # no audio stream
        return MagicMock()

    monkeypatch.setattr(video_thumbnail.subprocess, "run", fake_run)

    video_thumbnail.prepend_thumbnail_frame(str(video_path), str(image_path), out_path)

    assert len(calls) == 3
    ffmpeg_cmd = calls[2]
    assert "-an" in ffmpeg_cmd
    assert "-c:a" not in ffmpeg_cmd
    filter_complex = ffmpeg_cmd[ffmpeg_cmd.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0" in filter_complex
    assert "[outa]" not in ffmpeg_cmd


def test_prepend_thumbnail_frame_falls_back_to_30fps_on_unparseable_rate(tmp_path, monkeypatch):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake video")
    image_path = tmp_path / "thumb.png"
    from PIL import Image

    Image.new("RGB", (200, 200), (0, 0, 255)).save(image_path)
    out_path = tmp_path / "out.mp4"

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffprobe":
            if "v:0" in cmd:
                return _probe_result("200\n200\nnot-a-fraction\n")
            return _probe_result("")
        return MagicMock()

    monkeypatch.setattr(video_thumbnail.subprocess, "run", fake_run)

    # Should not raise despite the unparseable frame rate — falls back to 30fps.
    video_thumbnail.prepend_thumbnail_frame(str(video_path), str(image_path), out_path)
