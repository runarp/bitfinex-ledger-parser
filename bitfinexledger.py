#!/usr/bin/env python3
"""
Bitfinex has a ledger of truth, it's big, it's ugly but it captures all
movement of funds in/around/out of accounts.

While it lacks some key data such as order-id and margin trades it does provide
an anchor for your accounting.

But in order to be useful, we have to parse all the things.

"""
import re
import sys
import csv
import pathlib
import argparse
import typing

OW = r" on wallet (\w+)$"
FLAGS = re.I


# We map a 'type' to Regular Expressions.  This is the only place to add more match rules.
BITFINEX_RE = {
    "exchange": re.compile(
        r"^Exchange (?P<amount>\d+(\.\d+)?) (?P<symbol>\w+) for (?P<currency>\w+) @ (?P<rate>\d+(\.[\de-]+)?)"+OW,
        FLAGS
    ),
    "adjustment": re.compile(
        r"^Adjustment #(?P<id>\d+)"+OW,
        FLAGS
    ),
    "airdrop": re.compile(
        r"^(?P<coin>\w+) (?P<event>airdrop|distribution)"+OW,
        FLAGS
    ),
    "affiliate-rebate": re.compile(
        r"^Affiliate Rebate \(lev:(?P<level>\d),rebate:(?P<rate>\d+.\d+)%\)"+OW,
        FLAGS
    ),
    "snapshot": re.compile(
        r"^(?P<coin>.*) snapshot step(\d)"+OW,
        FLAGS
    ),
    "token-redemption": re.compile(
        r"^(?P<coin>.*) token redemption of (?P<percent>\d+(.\d+)?)%"+OW,
        FLAGS
    ),
    "hacked": re.compile(
        r"^Extraordinary loss adj of (?P<amount>\d+(\.\d+)?) (?P<currency>.*) for (?P<iou_token_amount>\d+(\.\d+)?)"
        r" (?P<iou_token>\w+) @ (?P<exchange_rate>\d+(\.\d+)?)"+OW,
        FLAGS
    ),
    "used-margin": re.compile(
        r"^Used Margin Funding Charge on wallet margin",
        FLAGS
    ),
    "unused-margin": re.compile(
        r"^Unused Margin Funding (Charge|Fee) on wallet margin$",
        FLAGS
    ),
    "margin-funding-payment": re.compile(
        r"^Margin Funding Payment"+OW,
        FLAGS
    ),
    "margin-funding-event": re.compile(
        r"^Funding Event (?P<pair>[\w:\d]+) \((?P<amount>\d+(\.\d+)?)\)"+OW,
        FLAGS
    ),
    "margin-funding-cost": re.compile(
        r"^Position #(?P<id>\d+) funding cost"+OW,
        FLAGS
    ),
    "position-cost": re.compile(
        r"^Position funding cost"+OW,
        FLAGS
    ),
    "close": re.compile(
        r"^Position closed @ (?P<amount>\d+(\.\d+)?)(?P<method> \(TRADE\))?"+OW,
        FLAGS
    ),
    "claimed": re.compile(
        r"^Position (#(?P<id>\d+) )?claimed @ (?P<price>\d+\.\d+)"+OW,
        FLAGS
    ),
    "claim-fee": re.compile(
        r"^Claiming fee for Position claimed (?P<pair>\w+) @ (?P<rate>\d+\.\d+)"+OW,
        FLAGS
    ),
    "claimed-no-id": re.compile(
        r"^Position claimed (?P<pair>\w+) @ (?P<rate>\d+\.\d+)"+OW,
        FLAGS
    ),
    "fees": re.compile(
        r"^Trading fees for (?P<amount>\d+(\.\d+)?) (?P<currency>\w+) (\((?P<pair>\w+)\) )?@ (?P<rate>\d+(\.\d+)?) "
        r"on (?P<exchange>\w+) \((?P<fee_rate>\d+\.\d+)%\)"+OW,
        FLAGS
    ),
    "claimed-fee": re.compile(
        r"^Position #(?P<id>\d+) claimed @ (?P<price>\d+\.\d+) \(fee: (?P<fee>\d+\.\d+) (?P<currency>\w+)\)"+OW,
        FLAGS),
    "interest": re.compile(
        r"^Interest Payment"+OW,
        FLAGS
    ),
    "settlement": re.compile(
        r"^Settlement @ (?P<rate>\d+\.\d+)"+OW,
        FLAGS
    ),
    "position-settlement": re.compile(
        r"^Position PL @ (?P<rate>\d+\.\d+) settlement \(trade\)"+OW,
        FLAGS
    ),
    "crypto-withdrawal-fee": re.compile(
        r"^Crypto Withdrawal fee"+OW,
        FLAGS
    ),
    "wire-withdrawal": re.compile(
        r"^Wire Transfer Withdrawal #(?P<id>\d+)"+OW,
        FLAGS
    ),
    "deposit": re.compile(
        r"^Deposit \((?P<coin>\w+)\) #(?P<id>\d+)"+OW,
        FLAGS
    ),
    "deposit-fee": re.compile(
        r"^Deposit Fee \((?P<source>\w+)\) (?P<id>\d+)"+OW,
        FLAGS
    ),
    "crypto-withdrawal": re.compile(
        r"^(?P<coin>\w+) (?P<action>Withdrawal) #(?P<id>\d+)"+OW,
        FLAGS
    ),
    "referral-bonus": re.compile(
        r"^Earned fees from user (?P<user>\d+)"+OW, FLAGS),

    "crypto-withdrawal-fees": re.compile(
        r"^Crypto Withdrawal fee"+OW,
        FLAGS
    ),
    "canceled-withdrawal": re.compile(
        r"^Canceled withdrawal (?P<reason>fee|request) #(?P<id>\d+)"+OW,
        FLAGS
    ),
    "swap-fees": re.compile(
        r"^Position #(?P<id>\d+) swap"+OW,
        FLAGS
    ),
    "transfer": re.compile(
        r"^Transfer of (?P<amount>\d+\.?\d*) (?P<currency>\w+) from wallet (?P<source>\w+) to (?P<target_type>\w+)"+OW,
        FLAGS
    ),
    "transfer-sub-account": re.compile(
        r"^Transfer of (?P<amount>\d+\.?\d*) (?P<cyy>\w+) from wallet (?P<source_type>\w+) to (?P<target_type>\w+)"
        r" SA\((?P<source_user>\d+)->(?P<target_user>\d+)\)"+OW,
        FLAGS
    ),
    "trading-rebate": re.compile(
        r"^Trading rebate for (?P<amount>\d+(\.\d+)?) (?P<currency>[\w\d]+) \((?P<pair>[\w:\d]+)\) @ "
        r"(?P<rate>\d+(\.\d+)?) on (?P<exchange>\w+) \((?P<rebate_rate>\d+.\d+)%\)"+OW,
        FLAGS
    ),
}

DATE_RE = re.compile(r"^(?P<yy>\d\d)-(?P<mm>\d\d)-(?P<dd>\d\d) (?P<HH>\d\d):(?P<MM>\d\d):(?P<ss>\d\d)$")


def load_file(file_name: typing.Union[pathlib.Path, str]) -> typing.Iterator:
    """
    Loads a File
    """
    file = pathlib.Path(file_name).expanduser()
    assert file.exists()
    
    with file.open("r") as fil:
        return load(fil)


def load(stream: typing.Iterable) -> typing.Iterator:
    header = None
    reader = csv.reader(stream)

    for row in reader:
        if header is None:
            header = [v.lower() for v in row]
            continue
        record = dict(zip(header, row))

        # y2100 FAIL
        record["date"] = "20" + record["date"]
        memo = record["description"]
        match = None

        for tx_type, rex in BITFINEX_RE.items():
            match = rex.match(memo)
            if match:
                record["type"] = tx_type
                record["meta"] = match.groupdict()
                yield record
                break

        if not match:
            print(f"Unable to Parse:\n{row}", file=sys.stderr)
            print(f"!!\n{memo}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser("Bitfinex Ledger Parser")
    parser.add_argument(
        "source",
        type=argparse.FileType("r")
    )
    parser.add_argument(
        "-o", "--out-file",
        type=argparse.FileType("w"),
        default="-"
    )
    parser.add_argument(
        "-t", "-f", "--format",
        choices=("json", "yaml"),
        default="yaml",
        help="Output format"
    )
    args = parser.parse_args()

    # Reads the entire contents, use 'load' directly if the file is too big.
    records = list(load(args.source))

    if args.format == "yaml":
        import yaml
        yaml.dump_all([records], stream=args.out_file)
        
    if args.format == "json":
        import json
        json.dump(records, fp=args.out_file, indent=2)


if __name__ == "__main__":
    main()
