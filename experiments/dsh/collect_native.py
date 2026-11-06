"""Download the native DSH outputs and original A+ archive; never resubmit."""
import asyncio,hashlib,json,zipfile,io
import argparse
from pathlib import Path
from PIL import Image,ImageDraw
from verify_native import client,STATE,read

async def main(args):
    c=await client()
    try:
        result=await read(c,args.request,args.session)
        folder=STATE/args.folder;folder.mkdir(exist_ok=True);files=[]
        latest={}
        for output in result['run'].get('result',{}).get('all_outputs',result['run']['outputs']):
            key=output.get('root_output_id') or output['id']
            if key not in latest or output['version']>latest[key]['version']:latest[key]=output
        outputs=list(latest.values())
        for i,o in enumerate(outputs,1):
            r=await c.get(o['download_url']);r.raise_for_status();p=folder/(f'{i:02d}-'+o['filename']);p.write_bytes(r.content)
            image=Image.open(p);image.verify();image=Image.open(p)
            files.append({'path':str(p),'asset_id':o['asset_id'],'output_id':o['id'],'job_id':o['job_id'],'width':image.width,'height':image.height,'sha256':hashlib.sha256(r.content).hexdigest(),'module':o.get('amazon_module')})
        plan=outputs[0]['amazon_module']['plan_id']
        archive=await c.get('/api/v1/agent/conversations/'+result['conversation']+'/amazon-plans/'+plan+'/archive');archive.raise_for_status()
        z=zipfile.ZipFile(io.BytesIO(archive.content));assert z.testzip() is None
        (folder/'Seattle-Aplus-native.zip').write_bytes(archive.content)
        canvas=Image.new('RGB',(1280,((len(files)+3)//4)*400),'#edf0f4');d=ImageDraw.Draw(canvas)
        for i,f in enumerate(files):
            image=Image.open(f['path']).convert('RGB');image.thumbnail((300,350));x=(i%4)*320;y=(i//4)*400
            canvas.paste(image,(x+(320-image.width)//2,y+28+(350-image.height)//2));d.text((x+8,y+8),f"{i+1} {f['width']}x{f['height']}",fill='#111111')
        canvas.save(folder/'contact.jpg',quality=92)
        (folder/'manifest.json').write_text(json.dumps({'ticket':result['ticket'],'conversation':result['conversation'],'run':result['run']['id'],'files':files,'zip_entries':z.namelist()},ensure_ascii=False,indent=2),encoding='utf-8')
        print('DELIVERED',len(files),'files ZIP',len(z.namelist()),str(folder/'contact.jpg'))
    finally:await c.aclose()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',default='native-real-aplus-v2');parser.add_argument('--session',default='native-product-v2');parser.add_argument('--folder',default='native-delivery');asyncio.run(main(parser.parse_args()))
