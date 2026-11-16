import os,sys,asyncio,subprocess,threading,http.server,functools,tempfile
from pathlib import Path
os.environ.setdefault("BOT_TOKEN","1:x")
import bot
def test_urls():
    ok=["https://www.youtube.com/watch?v=jNQXAC9IVRw","смотри https://youtu.be/abc123?t=5 круто","https://youtube.com/shorts/xyz","https://www.instagram.com/reel/ABC/?igsh=1","https://m.youtube.com/watch?v=1","https://music.youtube.com/watch?v=1"]
    for t in ok: assert bot.clean_url(t)[0],t
    assert bot.clean_url("https://evil.com/?u=youtube.com")==(None,"bad_host")
    assert bot.clean_url("https://youtube.com.evil.com/x")==(None,"bad_host")
    assert bot.clean_url("привет")==(None,"no_url")
    assert bot.clean_url("(https://youtu.be/a).")[0]=="https://youtu.be/a"
def test_errors():
    assert bot.classify_error("ERROR: Sign in to confirm you're not a bot")=="login"
    assert bot.classify_error("Video unavailable. This video is private")=="private"
    assert bot.classify_error("HTTP Error 403: Forbidden")=="blocked"
    assert bot.classify_error("boom")=="fail"
def test_pipeline():
    d=Path(tempfile.mkdtemp());src=d/"srv";src.mkdir()
    subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi","-i","testsrc=s=1280x720:r=30:d=6","-f","lavfi","-i","sine=f=440:d=6","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-shortest",str(src/"clip.mp4")],check=True)
    h=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(src))
    s=http.server.ThreadingHTTPServer(("127.0.0.1",0),h);threading.Thread(target=s.serve_forever,daemon=True).start()
    url=f"http://127.0.0.1:{s.server_port}/clip.mp4"
    out=d/"v";out.mkdir();p=bot.fetch_video(url,out,None,720)
    w,hh,du=bot.video_meta(p);assert p.suffix==".mp4" and hh<=720 and 5<=du<=7,(w,hh,du)
    out2=d/"a";out2.mkdir();a=bot.fetch_audio(url,out2,None,128)
    assert a.suffix==".mp3" and a.stat().st_size>10000
    s.shutdown()
if __name__=="__main__":
    for n,f in list(globals().items()):
        if n.startswith("test_"): f();print("ok",n)
