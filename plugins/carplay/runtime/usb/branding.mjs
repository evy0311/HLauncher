// Original HLauncher artwork, sent through the adapter's existing SendFile protocol.
import fs from 'node:fs';
import {SendFile, SendIconConfig, SendString, FileAddress} from './vendor/node-carplay/dist/modules/index.js';
const assets=new URL('../../../../hlauncher/ui/assets/branding/',import.meta.url);
export function brandingMessages() {
  // Validate all packaged artwork before changing anything on the adapter.
  const icons=[['hlauncher-256.png',FileAddress.OEM_ICON,256],
    ['hlauncher-120.png',FileAddress.ICON_120,120],
    ['hlauncher-180.png',FileAddress.ICON_180,180],
    ['hlauncher-256.png',FileAddress.ICON_250,256]].map(([file,path,size])=>{
      const data=fs.readFileSync(new URL(file,assets));
      if(data.length>256*1024 || !data.subarray(0,8).equals(Buffer.from('89504e470d0a1a0a','hex')) ||
          data.readUInt32BE(16)!==size || data.readUInt32BE(20)!==size)throw Error('Invalid packaged OEM icon');
      return new SendFile(data,path);
    });
  return [...icons,new SendString('HLauncher',FileAddress.BOX_NAME),new SendIconConfig({label:'HLauncher'})];
}
export async function applyBranding(driver,report=()=>{}) {
  report('sending');
  try {
    for(const message of brandingMessages()) {
      if(await driver.send(message)!==true)throw Error('Adapter USB transfer failed');
    }
    // USB completion is not a firmware read-back or proof the phone refreshed its cache.
    report('sent');return true;
  } catch(e) {report('failed',String(e).slice(0,160));return false;}
}
