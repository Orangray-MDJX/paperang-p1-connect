"""Bonjour/DNS-SD advertisement on one explicitly configured IPv4 interface."""
import asyncio
import socket
import uuid
from .config import find_ghostscript
from zeroconf import IPVersion, ServiceInfo
from zeroconf.asyncio import AsyncZeroconf


def printer_uuid():
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname()+'.paperang-p1'))


class Discovery:
    def __init__(self,cfg):
        self.cfg=cfg; self.zcs=[]; self.infos=[]
    async def start(self):
        cfg=self.cfg
        props={'txtvers':'1','qtotal':'1','rp':'ipp/print','ty':'Paperang P1',
               'product':'(Paperang P1)','pdl':'image/urf,image/pwg-raster,image/jpeg'+(',application/pdf' if find_ghostscript(cfg) else ''),
               'URF':'W8,RS300,DM1,IS1,V1.4','Color':'F','Duplex':'F',
               'UUID':printer_uuid(),'usb_MFG':'Paperang','usb_MDL':'P1',
               'note':'USB/Bluetooth bridge on '+socket.gethostname(),'priority':'0'}
        # All PTRs refer to the same base service instance and SRV/TXT records.
        for service in ('_ipp._tcp.local.','_universal._sub._ipp._tcp.local.','_print._sub._ipp._tcp.local.'):
            info=ServiceInfo(service,cfg.lan_name+'._ipp._tcp.local.',
                             addresses=[socket.inet_aton(cfg.lan_address)],port=cfg.ipp_port,
                             properties=props,server=socket.gethostname().replace('_','-')+'.local.')
            zc=AsyncZeroconf(interfaces=[cfg.lan_address],ip_version=IPVersion.V4Only)
            self.zcs.append(zc)
            await zc.async_register_service(info,allow_name_change=False,cooperating_responders=bool(self.infos))
            self.infos.append((zc,info))
    async def close(self):
        for zc,info in self.infos: await zc.async_unregister_service(info)
        for zc in self.zcs: await zc.async_close()
        self.zcs=[]; self.infos=[]
