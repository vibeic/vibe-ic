"""Read native ngspice real raw captures and integrate their actual time grid."""
from pathlib import Path
import gzip
import hashlib
import math
import os
import re

import numpy as np


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


class NativeRaw:
    def __init__(self, path, *, expected_raw_sha256=None, expected_raw_bytes=None):
        self.path=Path(path);header=[]
        compressed=self.path.suffix=='.gz'
        if compressed and (not re.fullmatch(r'[0-9a-f]{64}',str(expected_raw_sha256))
                or isinstance(expected_raw_bytes,bool) or not isinstance(expected_raw_bytes,int)
                or expected_raw_bytes<=0):
            raise ValueError('compressed native raw requires complete original identity')
        digest=hashlib.sha256()
        with (gzip.open(self.path,'rb') if compressed else self.path.open('rb')) as stream:
            while True:
                try:line=stream.readline(4*1024*1024+1)
                except EOFError as exc:raise ValueError('compressed native raw stream truncated') from exc
                if not line or stream.tell()>4*1024*1024:
                    raise ValueError('native raw header incomplete')
                digest.update(line)
                decoded=line.decode('utf-8').strip();header.append(decoded)
                if decoded in ('Binary:','Values:'):
                    offset=stream.tell();mode=decoded;break
            if compressed:
                if mode!='Binary:':raise ValueError('compressed native raw must have a binary payload')
                def dimension(key):
                    value=next((l.split(':',1)[1].strip() for l in header if l.startswith(key+':')),None)
                    if value is None or not value.isdigit() or int(value)<1:raise ValueError('native raw dimensions absent')
                    return int(value)
                expected=dimension('No. Points')*dimension('No. Variables')*8
                if expected_raw_bytes is not None and (isinstance(expected_raw_bytes,bool)
                        or not isinstance(expected_raw_bytes,int) or expected_raw_bytes!=offset+expected):
                    raise ValueError('native raw byte count differs from declared dimensions')
                payload=bytearray()
                while len(payload)<=expected:
                    try:part=stream.read(min(1024*1024,expected+1-len(payload)))
                    except EOFError as exc:raise ValueError('compressed native raw stream truncated') from exc
                    if not part:break
                    payload.extend(part);digest.update(part)
                if len(payload)!=expected:raise ValueError('native raw payload dimensions differ')
                if expected_raw_sha256 is not None and digest.hexdigest()!=expected_raw_sha256:
                    raise ValueError('decompressed native raw SHA differs')
        self.plot=next((l.split(':',1)[1].strip() for l in header if l.startswith('Plotname:')),'')
        flags=next((l.split(':',1)[1].split() for l in header if l.startswith('Flags:')),[])
        if 'real' not in flags or 'complex' in flags:raise ValueError('real native capture required')
        def count(key):
            value=next((l.split(':',1)[1].strip() for l in header if l.startswith(key+':')),None)
            if value is None or not value.isdigit() or int(value)<1:raise ValueError('native raw dimensions absent')
            return int(value)
        n,m=count('No. Points'),count('No. Variables')
        begin=header.index('Variables:')
        variables=[l.split() for l in header[begin+1:-1] if l]
        if len(variables)!=m or [int(v[0]) for v in variables]!=list(range(m)):
            raise ValueError('native raw variable indices differ')
        self.names=[re.sub(r'^v\((.*)\)$',r'\1',v[1].lower()) for v in variables]
        if len(set(self.names))!=m:raise ValueError('duplicate native raw vectors')
        self.index={name:i for i,name in enumerate(self.names)}
        if mode=='Binary:':
            if compressed:
                self.values=np.frombuffer(memoryview(payload).toreadonly(),dtype='<f8').reshape(n,m)
            else:
                if self.path.stat().st_size-offset!=n*m*8:raise ValueError('native raw payload dimensions differ')
                self.values=np.memmap(self.path,mode='r',dtype='<f8',offset=offset,shape=(n,m))
        else:
            with self.path.open() as stream:
                stream.seek(offset);lines=[l.split() for l in stream if l.strip()]
            if len(lines)!=n*m:raise ValueError('native ASCII payload dimensions differ')
            values=[]
            for point in range(n):
                if len(lines[point*m])!=2 or int(lines[point*m][0])!=point:
                    raise ValueError('native ASCII point index differs')
                values.extend(float(l[-1]) for l in lines[point*m:(point+1)*m])
            self.values=np.array(values).reshape(n,m)
        self.shape=(n,m)


    def row(self, index=0):
        values=self.values[index]
        if not np.all(np.isfinite(values)):raise ValueError('nonfinite native waveform value')
        return {**dict(zip(self.names,map(float,values))),'0':0.0}

    def take(self, values, names):
        columns=[self.index[name.lower()] if name!='0' else 0 for name in names]
        out=np.array(values[:,columns],copy=True)
        for i,name in enumerate(names):
            if name=='0':out[:,i]=0
        return out

    def segments(self, window, chunk=32):
        if self.plot!='Transient Analysis' or not self.names or self.names[0]!='time':
            raise ValueError('native transient time capture required')
        start,stop=window
        if not all(math.isfinite(v) for v in window) or not 0<=start<stop:
            raise ValueError('finite nonempty measurement window required')
        times=self.values[:,0]
        if not np.all(np.isfinite(times)) or np.any(np.diff(times)<=0):
            raise ValueError('native time grid is nonfinite or not strictly increasing')
        if times[0]>start or times[-1]<stop:raise ValueError('native capture does not cover measurement window')
        first=max(0,int(np.searchsorted(times,start))-1)
        last=min(len(times)-1,int(np.searchsorted(times,stop)))
        for index in range(first,last,chunk):
            end=min(last,index+chunk)
            t0=np.asarray(times[index:end]);t1=np.asarray(times[index+1:end+1])
            a=np.maximum(t0,start);b=np.minimum(t1,stop);keep=b>a
            x=np.asarray(self.values[index:end])[keep];y=np.asarray(self.values[index+1:end+1])[keep]
            if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
                raise ValueError('nonfinite native waveform value')
            yield b[keep]-a[keep],x,y,((a-t0)/(t1-t0))[keep],((b-t0)/(t1-t0))[keep]


def window_statistics(raw: NativeRaw, window, expressions, *, chunk=32):
    """Piecewise-linear integrals, never averages of adaptive sample points.

    Each expression is (positive-vector, negative-vector, divisor). Native
    resistor current is the two actual voltages divided by its emitted R.
    """
    left=[e[0] for e in expressions];right=[e[1] for e in expressions]
    divisor=np.array([e[2] for e in expressions],dtype=float)
    if np.any(~np.isfinite(divisor)) or np.any(divisor==0):raise ValueError('finite nonzero expression divisor required')
    count=len(expressions);integral=np.zeros(count);absolute=np.zeros(count);square=np.zeros(count)
    low=np.full(count,np.inf);high=np.full(count,-np.inf);duration=0.
    for dt,x,y,a,b in raw.segments(window,chunk):
        v0=(raw.take(x,left)-raw.take(x,right))/divisor
        v1=(raw.take(y,left)-raw.take(y,right))/divisor
        delta=v1-v0;u=v0+a[:,None]*delta;v=v0+b[:,None]*delta;weight=dt[:,None]
        integral+=np.sum(weight*(u+v)/2,axis=0)
        square+=np.sum(weight*(u*u+u*v+v*v)/3,axis=0)
        # Integrate |I| exactly across a linear segment's zero crossing.
        aa,bb=np.abs(u),np.abs(v);cross=u*v<0
        area=(aa+bb)/2
        np.divide(aa*aa+bb*bb,2*(aa+bb),out=area,where=cross)
        absolute+=np.sum(weight*area,axis=0)
        low=np.minimum(low,np.minimum(u,v).min(axis=0));high=np.maximum(high,np.maximum(u,v).max(axis=0))
        duration+=float(np.sum(dt))
    total=window[1]-window[0]
    if not math.isclose(duration,total,rel_tol=1e-12,abs_tol=0):raise ValueError('native waveform window has gaps')
    if any(np.any(~np.isfinite(value)) for value in (integral,absolute,square,low,high)):
        raise ValueError('nonfinite integrated native quantity')
    return [{'avg':float(integral[i]/total),'abs_avg':float(absolute[i]/total),
             'rms':float(np.sqrt(square[i]/total)),'min':float(low[i]),'max':float(high[i]),
             'peak_abs':float(max(abs(low[i]),abs(high[i])))} for i in range(count)]


def product_statistics(raw: NativeRaw, window, left, right):
    """Integrate a product of two measured piecewise-linear quantities."""
    total=window[1]-window[0];integral=0.;low=math.inf;high=-math.inf
    for dt,x,y,a,b in raw.segments(window):
        endpoints=[]
        for first,second,divisor in (left,right):
            if not math.isfinite(divisor) or divisor==0:raise ValueError('invalid product divisor')
            u=(raw.take(x,[first])-raw.take(x,[second]))[:,0]/divisor
            v=(raw.take(y,[first])-raw.take(y,[second]))[:,0]/divisor
            endpoints.append((u+a*(v-u),u+b*(v-u)))
        u0,u1=endpoints[0];v0,v1=endpoints[1]
        du,dv=u1-u0,v1-v0;c0=u0*v0;c1=u0*dv+v0*du;c2=du*dv
        integral+=float(np.sum(dt*(c0+c1/2+c2/3)))
        ends=c0+c1+c2;lo=np.minimum(c0,ends);hi=np.maximum(c0,ends)
        vertex=np.zeros_like(c0);np.divide(-c1,2*c2,out=vertex,where=c2!=0)
        inside=(c2!=0)&(vertex>0)&(vertex<1)
        value=c0+c1*vertex+c2*vertex*vertex
        lo=np.where(inside,np.minimum(lo,value),lo);hi=np.where(inside,np.maximum(hi,value),hi)
        low=min(low,float(lo.min()));high=max(high,float(hi.max()))
    if not all(math.isfinite(value) for value in (integral,low,high)):
        raise ValueError('nonfinite integrated native product')
    return {'avg':integral/total,'min':low,'max':high,'peak_abs':max(abs(low),abs(high))}


def native_capture(record, *, transient):
    """Select only a receipt-bound stored capture; legacy plain outputs stay valid."""
    outputs=record.get('outputs') or {};name='tran.raw' if transient else 'op.raw'
    metadata=record.get('native_raw')
    if metadata is None:
        selected=[Path(p) for p in outputs if p.endswith('/'+name)]
        if len(selected)!=1:raise ValueError('native capture absent or ambiguous')
        expected=outputs.get(str(selected[0]))
        if (not re.fullmatch(r'[0-9a-f]{64}',str(expected)) or not selected[0].is_file()
                or selected[0].is_symlink() or sha256(selected[0])!=expected):
            raise ValueError('plain native raw identity is absent, stale, or changed')
        return selected[0],{}
    required={'executed_path','stored_path','encoding','sha256','raw_sha256','raw_bytes'}
    if not isinstance(metadata,dict) or not required<=set(metadata) or metadata['encoding']!='gzip':
        raise ValueError('native raw storage metadata incomplete')
    executed,stored=Path(metadata['executed_path']),Path(metadata['stored_path'])
    if (executed.name!=name or stored.name!=name+'.gz'
            or os.path.abspath(executed.parent)!=os.path.abspath(stored.parent)
            or outputs.get(str(stored))!=metadata['sha256']):
        raise ValueError('stored native raw is not its declared output')
    if (not re.fullmatch(r'[0-9a-f]{64}',str(metadata['sha256']))
            or not stored.is_file() or stored.is_symlink() or sha256(stored)!=metadata['sha256']):
        raise ValueError('stored native raw archive identity is absent, stale, or changed')
    argv=record.get('argv') or []
    if (argv.count('-r')!=1 or argv.index('-r')+1>=len(argv)
            or os.path.abspath(argv[argv.index('-r')+1])!=os.path.abspath(executed)):
        raise ValueError('stored native raw is not bound to the executed native argv')
    if (not re.fullmatch(r'[0-9a-f]{64}',str(metadata['raw_sha256']))
            or isinstance(metadata['raw_bytes'],bool) or not isinstance(metadata['raw_bytes'],int)
            or metadata['raw_bytes']<=0):
        raise ValueError('original native raw identity incomplete')
    if any(p.endswith('/'+name) for p in outputs):
        raise ValueError('native raw storage outputs are ambiguous')
    return stored,{'expected_raw_sha256':metadata['raw_sha256'],'expected_raw_bytes':metadata['raw_bytes']}
