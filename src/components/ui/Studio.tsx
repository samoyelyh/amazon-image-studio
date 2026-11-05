import {useEffect,useRef,useState,type ButtonHTMLAttributes,type HTMLAttributes,type ReactNode} from 'react'

export function StudioButton({variant='secondary',className='',type='button',...props}:ButtonHTMLAttributes<HTMLButtonElement>&{variant?:'primary'|'secondary'|'danger'}){
  return <button {...props} type={type} data-variant={variant} className={`studio-button ${className}`}/>
}
export function StudioCard({className='',...props}:HTMLAttributes<HTMLElement>){return <section {...props} className={`studio-card ${className}`}/>}
export function StudioEmptyState({children}:{children:ReactNode}){return <div className="studio-empty" role="status">{children}</div>}

export function ResponsiveToolsPanel({title,children,className='',defaultOpen=false}:{title:string;children:ReactNode;className?:string;defaultOpen?:boolean}){
  const [open,setOpen]=useState(defaultOpen||typeof window!=='undefined'&&window.matchMedia('(min-width:1280px)').matches)
  useEffect(()=>{const media=window.matchMedia('(min-width:1280px)');const change=()=>setOpen(media.matches||defaultOpen);media.addEventListener('change',change);return()=>media.removeEventListener('change',change)},[defaultOpen])
  // Keep children mounted while collapsed: file inputs, edits and upload state survive.
  return <details className={`studio-tools ${className}`} open={open} onToggle={e=>setOpen(e.currentTarget.open)}><summary>{title}</summary><div className="studio-tools-content">{children}</div></details>
}

export function StudioDialog({label,children,onClose}:{label:string;children:ReactNode;onClose:()=>void}){
  const ref=useRef<HTMLDivElement>(null),close=useRef(onClose);close.current=onClose
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null
    ref.current?.focus()
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();close.current();return}
      if(event.key!=='Tab'||!ref.current)return
      const controls=Array.from(ref.current.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]')).filter(e=>e.getClientRects().length)
      const first=controls[0],last=controls[controls.length-1]
      if(!first){event.preventDefault();ref.current.focus()}
      else if(event.shiftKey&&(document.activeElement===first||document.activeElement===ref.current)){event.preventDefault();last.focus()}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
    }
    document.addEventListener('keydown',key)
    return()=>{document.removeEventListener('keydown',key);if(previous?.isConnected)previous.focus()}
  },[])
  return <div className="studio-dialog-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><div role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} ref={ref} className="studio-dialog">{children}</div></div>
}
