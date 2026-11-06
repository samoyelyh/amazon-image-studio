"""Reuse authorized original pixels in native A+ slots; never calls a provider."""
import hashlib
from io import BytesIO
from PIL import Image,ImageOps
from app.core.errors import AppError
from app.agents import amazon
from app.agents.adapters import chat
from app.agents.aplus_design import slots
from app.services.asset_service import read_asset_content

def render_crop(raw,box,size,background='#ffffff'):
    with Image.open(BytesIO(raw)) as opened:
        source=ImageOps.exif_transpose(opened).convert('RGB')
        w,h=source.size;l,t,r,b=box
        bounds=(round(l*w),round(t*h),round(r*w),round(b*h))
        if bounds[2]<=bounds[0] or bounds[3]<=bounds[1]:raise AppError('agent.crop_empty','原图裁切区域过小。',422)
        crop=source.crop(bounds);source_size=crop.size
        fitted=ImageOps.contain(crop,size,Image.Resampling.LANCZOS)
        canvas=Image.new('RGB',size,background);canvas.paste(fitted,((size[0]-fitted.width)//2,(size[1]-fitted.height)//2))
        out=BytesIO();canvas.save(out,format='PNG')
        return out.getvalue(),{'source_sha256':hashlib.sha256(raw).hexdigest(),'source_pixels':list(source_size),
            'source_bounds':list(bounds),'upscaled':fitted.width>source_size[0] or fitted.height>source_size[1],
            'processing':'original_source_crop_and_contain_no_generative_redraw'}

async def render(db,storage,conv,plan_id,module_id,slot_id):
    _,plan=await amazon.record(db,conv,plan_id)
    module=next((m for m in plan.modules if m.id==module_id),None)
    slot=next((s for s in slots(plan,module) if s['id']==slot_id),None) if module else None
    crop=slot['direction'].source_crop if slot else None
    if not crop:raise AppError('agent.source_crop_missing','原图复用槽位不存在。',404)
    asset=await chat.asset(db,conv.organization_id,conv.user_id,crop.asset_id)
    raw=await read_asset_content(asset,storage)
    size=(slot['spec']['width'],slot['spec']['height'])
    background=plan.creative_strategy.concept.canvas_color if plan.creative_strategy else '#ffffff'
    return render_crop(raw,crop.box,size,background)
