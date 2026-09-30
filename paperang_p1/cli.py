"""CLI client: share the running service's USB session and durable queue."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import httpx
from .config import Config


def build_parser():
    parser = argparse.ArgumentParser(prog='paperang', description='喵喵机 P1 本地服务客户端')
    parser.add_argument('-v', '--verbose', action='store_true')
    commands = parser.add_subparsers(dest='cmd', required=True)
    for name, help_text in [('status','查询状态'),('battery','查询电量'),('jobs','列出任务')]:
        commands.add_parser(name, help=help_text)
    scan = commands.add_parser('scan', help='扫描 BLE（USB 使用无需扫描）')
    scan.add_argument('--timeout', type=float, default=6)
    connect = commands.add_parser('connect', help='连接已配置的打印机')
    connect.add_argument('--transport', choices=['usb','auto','spp','ble','vendor'], default=None)
    power = commands.add_parser('set-power-off', help='设置自动关机秒数，off 为禁用，必须回读确认')
    power.add_argument('value')
    for name in ('job','cancel','resume'):
        command = commands.add_parser(name)
        command.add_argument('job_id', type=int)
    for name in ('selftest','print-text','print-image','print-file'):
        command = commands.add_parser(name)
        if name == 'print-text':
            command.add_argument('text')
            command.add_argument('--size', type=int)
        if name in ('print-image','print-file'): command.add_argument('path')
        if name == 'print-image': command.add_argument('--invert', action='store_true')
        command.add_argument('--density', type=int)
        command.add_argument('--dither', choices=['floyd-steinberg','atkinson','threshold'])
    return parser


async def execute(cfg, args):
    async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{cfg.api_port}/api', trust_env=False, timeout=120) as client:
        cmd = args.cmd
        method, path, payload = 'GET', '/status', None
        if cmd == 'scan': path = f'/scan?timeout={args.timeout}'
        elif cmd == 'jobs': path = '/jobs'
        elif cmd == 'job': path = f'/jobs/{args.job_id}'
        elif cmd in ('cancel','resume'): method, path, payload = 'POST', f'/jobs/{args.job_id}/{cmd}', {}
        elif cmd == 'connect': method, path, payload = 'POST', '/connect', {'transport':args.transport}
        elif cmd == 'set-power-off':
            seconds = 0 if args.value == 'off' else int(args.value)
            method, path, payload = 'POST', '/power-off', {'seconds':seconds}
        elif cmd in ('selftest','print-text','print-image','print-file'):
            method = 'POST'
            payload = {'density':args.density}
            if cmd == 'selftest':
                path, payload = '/selftest', {}
                query = []
                if args.density is not None: query.append(f'density={args.density}')
                if args.dither: query.append(f'dither={args.dither}')
                if query: path += '?' + '&'.join(query)
            elif cmd == 'print-text':
                path = '/print/text'
                payload.update(text=args.text.replace('\\n','\n'), font_size=args.size, dither=args.dither)
            else:
                path = '/print/image' if cmd == 'print-image' else '/print/file'
                payload.update(path=str(Path(args.path).resolve()), dither=args.dither)
                if cmd == 'print-image': payload['invert'] = args.invert
        response = await client.request(method,path,json=payload) if method != 'GET' else await client.get(path)
        if response.is_error: raise ValueError(f'服务返回 {response.status_code}: {response.text}')
        result = response.json()
        if cmd == 'battery':
            value = result.get('battery')
            print('未知' if value is None else f'{value:.0f}%')
        else: print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try: return asyncio.run(execute(Config.load(),args))
    except httpx.ConnectError:
        print('本地服务未运行，请先执行 .venv\\Scripts\\python.exe scripts\\run_service.py',file=sys.stderr)
        return 2
    except (httpx.HTTPError,ValueError,KeyboardInterrupt) as error:
        print(f'错误: {error}',file=sys.stderr)
        return 4


if __name__ == '__main__':
    raise SystemExit(main())
