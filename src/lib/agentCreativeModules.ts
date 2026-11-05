export type CreativeModule='auto'|'amazon_aplus'|'batch_tryon'|'listing_images'|'free_creation'|'image_edit'
export interface CreativeContext {module:CreativeModule;revision:number;label:string;primary_skills:string[];guidance:string}
export const creativeModules:Array<{id:CreativeModule;label:string}>=[{id:'auto',label:'自动选择'},{id:'amazon_aplus',label:'A+ 内容'},{id:'batch_tryon',label:'批量换衣'},{id:'listing_images',label:'商品主副图'},{id:'free_creation',label:'自由生图'},{id:'image_edit',label:'图片编辑'}]
export const automaticContext:CreativeContext={module:'auto',revision:0,label:'自动选择',primary_skills:[],guidance:''}
