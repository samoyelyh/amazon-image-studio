import AuthenticatedImage from './AuthenticatedImage'
import {StudioButton,StudioDialog} from './ui/Studio'
import type {Asset} from '../lib/contentApi'

export default function AssetPreviewDialog({asset,canDelete,onClose,onDownload,onDelete,categoryLabel}:{asset:Asset;canDelete:boolean;onClose:()=>void;onDownload:()=>void;onDelete:()=>void;categoryLabel?:string}){
  return <StudioDialog label="素材大图预览" onClose={onClose}>
    <div className="grid min-w-0 md:grid-cols-[minmax(0,1fr)_280px]">
      <div className="flex min-h-[32vh] items-center justify-center bg-stone-100 p-4"><AuthenticatedImage src={asset.url} alt={asset.filename} className="max-h-[76dvh] max-w-full object-contain"/></div>
      <aside className="flex min-w-0 flex-col gap-4 p-5"><StudioButton onClick={onClose} aria-label="关闭素材预览">关闭</StudioButton>
        <h2 className="break-all text-sm font-semibold">{asset.filename}</h2>
        {categoryLabel&&<span className="text-sm">{categoryLabel}</span>}
        <dl className="space-y-3 text-sm"><div><dt>图片尺寸</dt><dd>{asset.width}×{asset.height}</dd></div><div><dt>文件大小</dt><dd>{(asset.size/1024/1024).toFixed(2)} MB</dd></div></dl>
        <div className="mt-auto grid gap-2">{asset.url&&<StudioButton variant="primary" onClick={onDownload}>下载图片</StudioButton>}
          {canDelete&&<StudioButton variant="danger" onClick={onDelete}>删除素材</StudioButton>}</div>
      </aside>
    </div>
  </StudioDialog>
}
