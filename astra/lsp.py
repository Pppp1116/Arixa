import json, sys

def send(msg):
    b=json.dumps(msg).encode()
    sys.stdout.write(f"Content-Length: {len(b)}\r\n\r\n")
    sys.stdout.write(b.decode()); sys.stdout.flush()

def read_msg():
    headers={}
    while True:
        line=sys.stdin.readline()
        if not line: return None
        if line in ('\r\n','\n',''): break
        k,v=line.split(':',1); headers[k.lower().strip()]=v.strip()
    n=int(headers.get('content-length','0'))
    if n==0: return None
    return json.loads(sys.stdin.read(n))

def main(argv=None):
    while True:
        msg=read_msg()
        if not msg: break
        m=msg.get('method')
        if m=='initialize':
            send({'jsonrpc':'2.0','id':msg['id'],'result':{'capabilities':{'textDocumentSync':1,'hoverProvider':True}}})
        elif m=='textDocument/hover':
            send({'jsonrpc':'2.0','id':msg['id'],'result':{'contents':'Astra symbol'}})
        elif 'id' in msg:
            send({'jsonrpc':'2.0','id':msg['id'],'result':None})
