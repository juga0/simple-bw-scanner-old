from sbws.globals import (fail_hard, is_initted)
from sbws.lib.resultdump import Result
from sbws.lib.resultdump import ResultError
from sbws.lib.resultdump import ResultSuccess
from argparse import ArgumentDefaultsHelpFormatter
from statistics import median
import os
import json
import time


def read_result_file(fname, starting_dict=None):
    data = starting_dict if starting_dict else {}
    with open(fname, 'rt') as fd:
        for line in fd:
            d = json.loads(line)
            res = Result.from_dict(d)
            if isinstance(res, ResultError):
                continue
            assert isinstance(res, ResultSuccess)
            fp = d['fingerprint']
            if fp not in data:
                data[fp] = []
            data[fp].append(res)
    return data


class V3BWLine:
    def __init__(self, fp, bw, nick, rtts):
        self.fp = fp
        self.bw = bw
        self.nick = nick
        # convert to ms
        rtts = [round(r * 1000) for r in rtts]
        self.rtt = round(median(rtts))

    def __str__(self):
        frmt = 'node_id={fp} bw={sp} nick={n} rtt={rtt}'
        return frmt.format(fp=self.fp, sp=round(self.bw), n=self.nick,
                           rtt=self.rtt)


def result_data_to_v3bw_line(data, fingerprint):
    assert fingerprint in data
    results = data[fingerprint]
    for res in results:
        assert isinstance(res, ResultSuccess)
    results = data[fingerprint]
    nick = results[0].nickname
    speeds = [dl['amount'] / dl['duration']
              for r in results for dl in r.downloads]
    speed = median(speeds)
    rtts = [rtt for r in results for rtt in r.rtts]
    return V3BWLine(fingerprint, speed, nick, rtts)


def warn_if_not_accurate_enough(lines, constant):
    margin = 0.001
    accuracy_ratio = (sum([l.bw for l in lines]) / len(lines)) / constant
    log.info('The generated lines are within {:.5}% of what they should '
             'be'.format((1-accuracy_ratio)*100))
    if accuracy_ratio < 1 - margin or accuracy_ratio > 1 + margin:
        log.warn('There was {:.3}% error and only +/- {:.3}% is '
                 'allowed'.format((1-accuracy_ratio)*100, margin*100, 2))


def scale_lines(args, v3bw_lines):
    total = sum([l.bw for l in v3bw_lines])
    if not args.raw:
        scale = len(v3bw_lines) * args.scale_constant
    else:
        scale = total
    ratio = scale / total
    for line in v3bw_lines:
        line.bw = round(line.bw * ratio) + 1
    warn_if_not_accurate_enough(v3bw_lines, args.scale_constant)
    return v3bw_lines


def gen_parser(sub):
    p = sub.add_parser('generate',
                       formatter_class=ArgumentDefaultsHelpFormatter)
    p.add_argument('--output', default='/dev/stdout', type=str,
                   help='Where to write v3bw file')
    p.add_argument('--scale-constant', default=7500, type=int,
                   help='When scaling bw weights, scale them using this const '
                   'multiplied by the number of measured relays')
    p.add_argument('--raw', '--no-scale', action='store_true',
                   help='If specified, use bandwidth values as they are, with '
                   'no scaling')


def main(args, conf, log_):
    global log
    log = log_
    if not is_initted(args.directory):
        fail_hard('Sbws isn\'t initialized.  Try sbws init', log=log)

    datadir = conf['paths']['datadir']
    if not os.path.isdir(datadir):
        fail_hard(datadir, 'does not exist')
    if args.scale_constant < 1:
        fail_hard('--scale-constant must be positive')

    data_fnames = sorted(os.listdir(datadir), reverse=True)
    data_fnames = data_fnames[0:14]
    data_fnames = [os.path.join(datadir, f) for f in data_fnames]
    data = {}
    for fname in data_fnames:
        data = read_result_file(fname, data)
    data_lines = [result_data_to_v3bw_line(data, fp) for fp in data]
    data_lines = sorted(data_lines, key=lambda d: d.bw, reverse=True)
    data_lines = scale_lines(args, data_lines)
    with open(args.output, 'wt') as fd:
        fd.write('{}\n'.format(int(time.time())))
        for line in data_lines:
            fd.write('{}\n'.format(str(line)))
