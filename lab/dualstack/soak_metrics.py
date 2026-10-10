"""Coleta limitada: histogramas <=0,1% + 1 us; amostras comprimidas fora do loop."""
import array
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import struct
import threading
import time

# index, family, event, cumulative upload, scheduled/began/received/ended, bytes, ok
RECORD = struct.Struct('<IBBQddddI?')
STEP = math.log1p(.001)
BINS = 20000


class Histogram:
    def __init__(self):
        self.bins = array.array('Q', [0]) * BINS
        self.n = 0
        self.maximum = 0.0

    def add(self, value):
        assert math.isfinite(value) and value >= 0
        index = math.ceil(math.log1p(value * 1000) / STEP)
        assert index < BINS, 'histogram_range'
        self.bins[index] += 1
        self.n += 1
        self.maximum = max(self.maximum, value)

    def summary(self):
        result = {'count': self.n, 'max': self.maximum if self.n else None}
        for name, quantile in [('p50', .5), ('p95', .95), ('p99', .99)]:
            target = math.ceil(self.n * quantile)
            count = 0
            result[name] = None
            if target:
                for i, n in enumerate(self.bins):
                    count += n
                    if count >= target:
                        result[name] = min(self.maximum, math.expm1(i * STEP) / 1000)
                        break
        return result


class Metrics:
    def __init__(self):
        self.histograms = {k: Histogram() for k in ['response_ms', 'latency_ms', 'queue_ms', 'total_ms']}
        self.count = 0

    def add(self, scheduled, began, received, ended):
        for name, value in [('response_ms', received-began), ('latency_ms', ended-began),
                            ('queue_ms', max(0, began-scheduled)), ('total_ms', max(0, ended-scheduled))]:
            self.histograms[name].add(value * 1000)
        self.count += 1

    def summary(self):
        return {name: h.summary() for name, h in self.histograms.items()}


class Samples:
    """No máximo 16 blocos de 1.000 amostras aguardam o escritor."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(exist_ok=False)
        self.queue = queue.Queue(maxsize=16)
        self.buffer = bytearray()
        self.error = None
        self.peak_queue = 0
        self.count = 0
        self.thread = threading.Thread(target=self.writer, daemon=True)
        self.thread.start()

    def submit(self, item):
        if self.error:
            raise RuntimeError('sample_writer_failed') from self.error
        self.queue.put_nowait(item)
        self.peak_queue = max(self.peak_queue, self.queue.qsize())

    def add(self, *row):
        self.buffer.extend(RECORD.pack(*row))
        self.count += 1
        if len(self.buffer) >= 1000 * RECORD.size:
            self.submit(bytes(self.buffer))
            self.buffer.clear()

    def segment(self):
        if self.buffer:
            self.submit(bytes(self.buffer))
            self.buffer.clear()
        done = threading.Event()
        self.submit(done)
        deadline=time.monotonic()+30
        while not done.wait(.1):
            if self.error or time.monotonic()>deadline:
                raise RuntimeError('sample_segment_failed')
        if self.error:raise RuntimeError('sample_segment_failed')

    def close(self):
        self.segment()
        self.submit(None)
        self.thread.join(30)
        assert not self.thread.is_alive() and not self.error, 'sample_close_failed'

    def writer(self):
        raw = compressed = None
        number = 0
        records = 0
        try:
            while True:
                item = self.queue.get()
                if isinstance(item, bytes):
                    if raw is None:
                        part = self.directory / f'{number:05d}.bin.gz.partial'
                        raw = part.open('xb')
                        compressed = gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=1, mtime=0)
                    compressed.write(item)
                    records += len(item) // RECORD.size
                else:
                    if raw is not None:
                        compressed.close()
                        raw.flush()
                        os.fsync(raw.fileno())
                        raw.close()
                        final = part.with_suffix('')
                        os.replace(part, final)
                        h = hashlib.sha256()
                        with final.open('rb') as f:
                            while data := f.read(1024 * 1024):
                                h.update(data)
                        with (self.directory / 'manifest.jsonl').open('a') as f:
                            f.write(json.dumps({'file': final.name, 'records': records,
                                                'bytes': final.stat().st_size, 'sha256': h.hexdigest()})+'\n')
                            f.flush()
                            os.fsync(f.fileno())
                        fd = os.open(self.directory, os.O_DIRECTORY)
                        os.fsync(fd)
                        os.close(fd)
                        raw = compressed = None
                        records = 0
                        number += 1
                    if item is None:
                        break
                    item.set()
        except BaseException as error:
            self.error = error
        finally:
            if compressed:
                compressed.close()
            if raw:
                raw.close()
