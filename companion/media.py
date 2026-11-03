"""Non-destructive classroom/storage copies; exact executable argv, never a shell."""
import json, re, subprocess
from fractions import Fraction
from pathlib import Path

def probe(path):
    p=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-show_chapters','-of','json',str(path)],capture_output=True,timeout=60)
    if p.returncode:raise RuntimeError('Media validation failed')
    return json.loads(p.stdout)

def av1_options():
    """Select an AV1 encoder actually present in the current FFmpeg."""
    try:
        result=subprocess.run(['ffmpeg','-hide_banner','-encoders'],capture_output=True,text=True,timeout=30)
    except (OSError,subprocess.TimeoutExpired) as e:
        raise RuntimeError('Could not check the local AV1 encoder.') from e
    if result.returncode:raise RuntimeError('Could not check the local AV1 encoder.')
    names=set(re.findall(r'^\s*[A-Z.]{6}\s+(libaom-av1|libsvtav1)\s',result.stdout,re.MULTILINE))
    if 'libaom-av1' in names:return ['-c:v','libaom-av1','-crf','32','-b:v','0','-cpu-used','6','-pix_fmt','yuv420p']
    if 'libsvtav1' in names:return ['-c:v','libsvtav1','-crf','32','-preset','6','-pix_fmt','yuv420p']
    raise RuntimeError('This FFmpeg has no supported AV1 encoder. Original retained in the local job folder.')

def copy_plan(source, mode, source_url=None):
    info=probe(source);video=next((s for s in info['streams'] if s['codec_type']=='video'),None)
    if not video:return None,'Audio-only: no video copy needed'
    if mode=='none':return None,'Original retained; compression disabled'
    height=video.get('height',0);codec=video.get('codec_name','')
    if mode=='av1' and (height<720 or codec in ('av1','hevc','vp9')):return None,'Storage copy skipped: low-resolution or already efficient source'
    dest=Path(source).with_name('classroom.mp4' if mode=='classroom' else 'storage-av1.mp4')
    args=['ffmpeg','-nostdin','-hide_banner','-v','error','-n','-i',str(source),'-map','0:v:0','-map','0:a?','-map','0:s?','-map_metadata','0','-map_chapters','0']
    if mode=='classroom' and codec=='h264' and height<=1080 and video.get('pix_fmt')=='yuv420p':args+=['-c:v','copy']
    else:
        args+=['-vf',"scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"]
        args+=['-c:v','libx264','-crf','20','-preset','medium','-pix_fmt','yuv420p'] if mode=='classroom' else av1_options()
    audio=[s for s in info['streams'] if s['codec_type']=='audio']
    if source_url:args+=['-metadata','comment='+source_url]
    args+=['-c:a','copy' if all(s.get('codec_name')=='aac' for s in audio) else 'aac','-c:s','mov_text','-movflags','+faststart',str(dest)]
    return (args,dest,info),'Original frame rate preserved; no frame-rate conversion'

def standard_plan(source, quality='720', include_subtitles=True, codec='h264'):
    """Build a compatible MP4 without changing the source or its frame rate."""
    info=probe(source)
    video=next((s for s in info['streams'] if s.get('codec_type')=='video'),None)
    if not video:raise RuntimeError('Source has no video track')
    audio=[s for s in info['streams'] if s.get('codec_type')=='audio']
    cap=None if quality=='best' else int(quality)
    w,h=video.get('width',0),video.get('height',0)
    compatible=(codec=='h264' and video.get('codec_name')=='h264' and video.get('pix_fmt')=='yuv420p' and (cap is None or (w and h and min(w,h)<=cap)))
    dest=Path(source).with_name('standard-output.mp4')
    args=['ffmpeg','-nostdin','-hide_banner','-v','error','-n','-i',str(source),'-map','0:v:0','-map','0:a?']
    if include_subtitles:args+=['-map','0:s?']
    args+=['-map_metadata','0','-map_chapters','0']
    if compatible:args+=['-c:v','copy']
    else:
        if cap:args+=['-vf',f"scale=w='if(gte(iw,ih),min(iw,{cap}*iw/ih),min(iw,{cap}))':h='if(gte(iw,ih),min(ih,{cap}),min(ih,{cap}*ih/iw))':force_original_aspect_ratio=decrease:force_divisible_by=2"]
        args+=['-c:v','libx264','-crf','20','-preset','medium','-pix_fmt','yuv420p'] if codec=='h264' else av1_options()
    args+=['-c:a','copy' if all(s.get('codec_name')=='aac' for s in audio) else 'aac']
    if include_subtitles:args+=['-c:s','mov_text']
    args+=['-movflags','+faststart',str(dest)]
    return args,dest,info

def validate_copy(source_info,dest,source,mode, runner=None):
    info=probe(dest)
    duration=float(source_info['format'].get('duration',0));out=float(info['format'].get('duration',0))
    if duration and abs(out-duration)>max(1,duration*.01):raise RuntimeError('Copy duration mismatch')
    for typ in ('audio','subtitle'):
        if sum(x['codec_type']==typ for x in info['streams'])<sum(x['codec_type']==typ for x in source_info['streams']):raise RuntimeError('Copy lost media tracks')
    if len(info.get('chapters',[]))<len(source_info.get('chapters',[])):raise RuntimeError('Copy lost chapters')
    a=next((x for x in source_info['streams'] if x['codec_type']=='video'),None);b=next((x for x in info['streams'] if x['codec_type']=='video'),None)
    if a and not b:raise RuntimeError('Copy lost video track')
    if a and b:
        # Matroska millisecond timestamps can slightly change reported average on MP4 remux.
        try:fa=float(Fraction(a.get('avg_frame_rate','0/1')));fb=float(Fraction(b.get('avg_frame_rate','0/1')))
        except (ValueError,ZeroDivisionError):fa=fb=0
        if fa and abs(fa-fb)/fa>.002:raise RuntimeError('Copy changed frame rate')
    # Full decode validation catches truncation/corrupt frame payload beyond ffprobe headers.
    args=['ffmpeg','-nostdin','-v','error','-xerror','-i',str(dest),'-map','0:v?','-map','0:a?','-f','null','-']
    if runner:
        code=runner(args)
        if code is None:raise InterruptedError('Copy validation interrupted')
        if code:raise RuntimeError('Copy decode validation failed')
    else:
        p=subprocess.run(args,capture_output=True,timeout=7200)
        if p.returncode or p.stderr:raise RuntimeError('Copy decode validation failed')
    if mode=='standard' and b:
        if b.get('codec_name')!='h264' or b.get('pix_fmt')!='yuv420p':raise RuntimeError('MP4 video is not H.264 yuv420p')
        if any(x.get('codec_name')!='aac' for x in info['streams'] if x.get('codec_type')=='audio'):raise RuntimeError('MP4 audio is not AAC')
    if mode in ('av1','av1-output') and b:
        if b.get('codec_name')!='av1' or b.get('pix_fmt')!='yuv420p':raise RuntimeError('Output video is not AV1 yuv420p')
        if any(x.get('codec_name')!='aac' for x in info['streams'] if x.get('codec_type')=='audio'):raise RuntimeError('AV1 output audio is not AAC')
    if mode=='av1' and dest.stat().st_size>Path(source).stat().st_size*.85:return False
    return True
