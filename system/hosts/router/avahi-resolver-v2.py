#!/usr/bin/env python3
#
# A plugin for the Unbound DNS resolver to resolve DNS records in
# multicast DNS [RFC 6762] via Avahi.
# Modified by chayleaf to resolve addresses and import them into
# nftables.
#
# Copyright (C) 2018-2019 Internet Real-Time Lab, Columbia University
# http://www.cs.columbia.edu/irt/
#
# Written by Jan Janak <janakj@cs.columbia.edu>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
#
# Dependendies:
#   Unbound with pythonmodule configured for Python 3
#   dnspython [http://www.dnspython.org]
#   pydbus [https://github.com/LEW21/pydbus]
#
# To enable Python 3 support, configure Unbound as follows:
#   PYTHON_VERSION=3 ./configure --with-pythonmodule
#
# The plugin in meant to be used as a fallback resolver that resolves
# records in multicast DNS if the upstream server cannot be reached or
# provides no answer (NXDOMAIN).
#
# mDNS requests for negative records, i.e., records for which Avahi
# returns no answer (NXDOMAIN), are expensive. Since there is no
# single authoritative server in mDNS, such requests terminate only
# via a timeout. The timeout is about a second (if MDNS_TIMEOUT is not
# configured), or the value configured via MDNS_TIMEOUT. The
# corresponding Unbound thread will be blocked for this amount of
# time. For this reason, it is important to configure an appropriate
# number of threads in unbound.conf and limit the RR types and names
# that will be resolved via Avahi via the environment variables
# described later.
#
# An example unbound.conf with the plugin enabled:
#
# | server:
# |   module-config: "validator python iterator"
# |   num-threads: 32
# |   cache-max-negative-ttl: 60
# |   cache-max-ttl: 60
# | python:
# |   python-script: path/to/this/file
#
#
# The plugin can also be run interactively. Provide the name and
# record type to be resolved as command line arguments and the
# resolved record will be printed to standard output:
#
#   $ ./avahi-resolver.py voip-phx4.phxnet.org A
#   voip-phx4.phxnet.org. 120 IN A 10.4.3.2
#
#
# The behavior of the plugin can be controlled via the following
# environment variables:
#
# DBUS_SYSTEM_BUS_ADDRESS
#
# The address of the system DBus bus, in the format expected by DBus,
# e.g., unix:path=/run/avahi/system-bus.sock
#
#
# DEBUG
#
# Set this environment variable to "yes", "true", "on", or "1" to
# enable debugging. In debugging mode, the plugin will output a lot
# more information about what it is doing either to the standard
# output (when run interactively) or to Unbound via log_info and
# log_error.
#
# By default debugging is disabled.
#
#
# MDNS_TTL
#
# Avahi does not provide the TTL value for the records it returns.
# This environment variable can be used to configure the TTL value for
# such records.
#
# The default value is 120 seconds.
#
#
# MDNS_TIMEOUT
#
# The maximum amount of time (in milliseconds) an Avahi request is
# allowed to run. This value sets the time it takes to resolve
# negative (non-existent) records in Avahi. If unset, the request
# terminates when Avahi sends the "AllForNow" signal, telling the
# client that more records are unlikely to arrive. This takes roughly
# about one second. You may need to configure a longer value here on
# slower networks, e.g., networks that relay mDNS packets such as
# MANETs.
#
#
# MDNS_GETONE
#
# If set to "true", "1", or "on", an Avahi request will terminate as
# soon as at least one record has been found. If there are multiple
# nodes in the mDNS network publishing the same record, only one (or
# subset) will be returned.
#
# If set to "false", "0", or "off", the plugin will gather records for
# MDNS_TIMEOUT and return all records found. This is only useful in
# networks where multiple nodes are known to publish different records
# under the same name and the client needs to be able to obtain them
# all. When configured this way, all Avahi requests will always take
# MDNS_TIMEOUT to complete!
#
# This option is set to true by default.
#
#
# MDNS_REJECT_TYPES
#
# A comma-separated list of record types that will NOT be resolved in
# mDNS via Avahi. Use this environment variable to prevent specific
# record types from being resolved via Avahi. For example, if your
# network does not support IPv6, you can put AAAA on this list.
#
# The default value is an empty list.
#
# Example: MDNS_REJECT_TYPES=aaaa,mx,soa
#
#
# MDNS_ACCEPT_TYPES
#
# If set, a record type will be resolved via Avahi if and only if it
# is present on this comma-separated list. In other words, this is a
# whitelist.
#
# The default value is an empty list which means all record types will
# be resolved via Avahi.
#
# Example: MDNS_ACCEPT_TYPES=a,ptr,txt,srv,aaaa,cname
#
#
# MDNS_REJECT_NAMES
#
# If the name being resolved matches the regular expression in this
# environment variable, the name will NOT be resolved via Avahi. In
# other words, this environment variable provides a blacklist.
#
# The default value is empty--no names will be reject.
#
# Example: MDNS_REJECT_NAMES=(^|\.)example\.com\.$
#
#
# MDNS_ACCEPT_NAMES
#
# If set to a regular expression, a name will be resolved via Avahi if
# and only if it matches the regular expression. In other words, this
# variable provides a whitelist.
#
# The default value is empty--all names will be resolved via Avahi.
#
# Example: MDNS_ACCEPT_NAMES=^.*\.example\.com\.$
#

import gi
import os
import pydbus
import re
import array
import threading
import traceback
import dns.rdata
import dns.rdatatype
import dns.rdataclass

from collections.abc import Callable
from dns.rcode import Rcode
from dns.rdataclass import RdataClass
from dns.rdatatype import RdataType
from queue import Queue
from gi.repository import GLib
from pydbus import SystemBus
from typing import TypedDict, Optional, Any


IF_UNSPEC = -1
PROTO_UNSPEC = -1

DOMAIN_NAME_OVERRIDES: dict[str, str] = {}
DEBUG = False
MDNS_TTL: int
MDNS_GETONE: bool
MDNS_TIMEOUT: Optional[int]
MDNS_REJECT_TYPES: list[RdataType]
MDNS_ACCEPT_TYPES: list[RdataType]
MDNS_REJECT_NAMES: Optional[re.Pattern]
MDNS_ACCEPT_NAMES: Optional[re.Pattern]

sysbus: pydbus.bus.Bus
avahi: Any  # pydbus.proxy.ProxyObject
trampoline: dict[str, "RecordBrowser"] = dict()
thread_local = threading.local()
dbus_thread: threading.Thread
dbus_loop: Any


def str2bool(v: str) -> bool:
    if v.lower() in ["false", "no", "0", "off", ""]:
        return False
    return True


def dbg(msg: str) -> None:
    if DEBUG != False:
        log_info(f"avahi-resolver: {msg}")


#
# Although pydbus has an internal facility for handling signals, we
# cannot use that with Avahi. When responding from an internal cache,
# Avahi sends the first signal very quickly, before pydbus has had a
# chance to subscribe for the signal. This will result in lost signal
# and missed data:
#
# https://github.com/LEW21/pydbus/issues/87
#
# As a workaround, we subscribe to all signals before creating a
# record browser and do our own signal matching and dispatching via
# the following function.
#
def signal_dispatcher(connection, sender, path: str, interface, name, args) -> None:
    o = trampoline.get(path, None)
    if o is None:
        return

    if name == "ItemNew":
        o.itemNew(*args)
    elif name == "ItemRemove":
        o.itemRemove(*args)
    elif name == "AllForNow":
        o.allForNow(*args)
    elif name == "Failure":
        o.failure(*args)


class RecordBrowser:
    def __init__(
        self,
        callback: Callable[
            [list[tuple[str, RdataClass, RdataType, bytes]], Optional[Exception]], None
        ],
        name: str,
        type_: RdataType,
        timeout: Optional[int] = None,
        getone: bool = True,
    ):
        self.callback = callback
        self.records: list[tuple[str, RdataClass, RdataType, bytes]] = []
        self.error: Optional[Exception] = None
        self.getone: bool = getone
        name1: str = DOMAIN_NAME_OVERRIDES.get(name, name)
        if name1 != name:
            self.overrides: dict[str, str] = {
                name1: name,
            }
            if name.endswith(".") and name1.endswith("."):
                self.overrides[name1[:-1]] = name[:-1]
        else:
            self.overrides = {}

        self.timer = (
            None if timeout is None else GLib.timeout_add(timeout, self.timedOut)
        )

        self.browser_path: str = avahi.RecordBrowserNew(
            IF_UNSPEC, PROTO_UNSPEC, name1, dns.rdataclass.IN, type_, 0
        )
        trampoline[self.browser_path] = self
        self.browser = sysbus.get(".Avahi", self.browser_path)
        self.dbg(
            f"Created RecordBrowser(name={name1}, type={dns.rdatatype.to_text(type_)}, getone={getone}, timeout={timeout})"
        )

    def dbg(self, msg: str):
        dbg(f"[{self.browser_path}] {msg}")

    def _done(self) -> None:
        del trampoline[self.browser_path]
        self.dbg("Freeing")
        self.browser.Free()

        if self.timer is not None:
            self.dbg("Removing timer")
            GLib.source_remove(self.timer)

        self.callback(self.records, self.error)

    def itemNew(
        self,
        interface: int,
        protocol: int,
        name: str,
        class_: int,
        type_: int,
        rdata: bytes,
        flags: int,
    ):
        self.dbg("Got signal ItemNew")
        self.records.append(
            (
                self.overrides.get(name, name),
                RdataClass(class_),
                RdataType(type_),
                rdata,
            )
        )
        if self.getone:
            self._done()

    def itemRemove(
        self,
        interface: int,
        protocol: int,
        name: str,
        class_: int,
        type_: int,
        rdata: bytes,
        flags: int,
    ):
        self.dbg("Got signal ItemRemove")
        self.records.remove(
            (
                self.overrides.get(name, name),
                RdataClass(class_),
                RdataType(type_),
                rdata,
            )
        )

    def failure(self, error: str):
        self.dbg("Got signal Failure")
        self.error = Exception(error)
        self._done()

    def allForNow(self) -> None:
        self.dbg("Got signal AllForNow")
        if self.timer is None:
            self._done()

    def timedOut(self) -> bool:
        self.dbg("Timed out")
        self._done()
        return False


#
# This function runs the main event loop for DBus (GLib). This
# function must be run in a dedicated worker thread.
#
def dbus_main() -> None:
    global sysbus, avahi, dbus_loop

    dbg("Connecting to system DBus")
    sysbus = SystemBus()

    dbg("Subscribing to .Avahi.RecordBrowser signals")
    sysbus.con.signal_subscribe(
        "org.freedesktop.Avahi",
        "org.freedesktop.Avahi.RecordBrowser",
        None,
        None,
        None,
        0,
        signal_dispatcher,
    )

    avahi = sysbus.get(".Avahi", "/")

    dbg(
        f"Connected to Avahi Daemon: {avahi.GetVersionString()} (API {avahi.GetAPIVersion()}) [{avahi.GetHostNameFqdn()}]"
    )

    dbg("Starting DBus main loop")
    dbus_loop = GLib.MainLoop()
    dbus_loop.run()


#
# This function must be run in the DBus worker thread. It creates a
# new RecordBrowser instance and once it has finished doing it thing,
# it will send the result back to the original thread via the queue.
#
def start_resolver(
    queue: Queue[
        (
            tuple[list[tuple[str, RdataClass, RdataType, bytes]], None]
            | tuple[None, Exception]
        )
    ],
    name: str,
    type_: RdataType,
    timeout: Optional[int] = None,
    getone: bool = True,
) -> bool:
    try:
        RecordBrowser(lambda *v: queue.put_nowait(v), name, type_, timeout, getone)
    except Exception as e:
        queue.put_nowait((None, e))

    return False


#
# To resolve a request, we setup a queue, post a task to the DBus
# worker thread, and wait for the result (or error) to arrive over the
# queue. If the worker thread reports an error, raise the error as an
# exception.
#
def resolve(
    name: str, type_: RdataType, timeout: Optional[int] = None, getone: bool = True
) -> list[tuple[str, RdataClass, RdataType, bytes]]:
    try:
        queue: Queue[
            (
                tuple[list[tuple[str, RdataClass, RdataType, bytes]], None]
                | tuple[None, Exception]
            )
        ] = thread_local.queue
    except AttributeError:
        dbg("Creating new per-thread queue")
        queue = Queue()
        thread_local.queue = queue

    GLib.idle_add(lambda: start_resolver(queue, name, type_, timeout, getone))

    records, error = queue.get()
    queue.task_done()

    if error is not None:
        raise error

    assert records is not None
    return records


def parse_type_list(lst: str) -> list[RdataType]:
    return list(
        map(dns.rdatatype.from_text, [v.strip() for v in lst.split(",") if len(v)])
    )


def init(*args: Any, **kwargs: Any):
    global dbus_thread, DEBUG
    global MDNS_TTL, MDNS_GETONE, MDNS_TIMEOUT
    global MDNS_REJECT_TYPES, MDNS_ACCEPT_TYPES
    global MDNS_REJECT_NAMES, MDNS_ACCEPT_NAMES

    domain_name_overrides: str = os.environ.get("DOMAIN_NAME_OVERRIDES", "")
    if domain_name_overrides:
        for kv in domain_name_overrides.split(";"):
            k1, v1 = kv.split("->")
            DOMAIN_NAME_OVERRIDES[k1] = v1
            DOMAIN_NAME_OVERRIDES[k1 + "."] = v1 + "."

    DEBUG = str2bool(os.environ.get("DEBUG", str(False)))

    MDNS_TTL = int(os.environ.get("MDNS_TTL", 120))
    dbg(f"TTL for records from Avahi: {MDNS_TTL}")

    MDNS_REJECT_TYPES = parse_type_list(os.environ.get("MDNS_REJECT_TYPES", ""))
    if MDNS_REJECT_TYPES:
        dbg(f"Types NOT resolved via Avahi: {MDNS_REJECT_TYPES}")

    MDNS_ACCEPT_TYPES = parse_type_list(os.environ.get("MDNS_ACCEPT_TYPES", ""))
    if MDNS_ACCEPT_TYPES:
        dbg(f"ONLY resolving the following types via Avahi: {MDNS_ACCEPT_TYPES}")

    v = os.environ.get("MDNS_REJECT_NAMES", None)
    MDNS_REJECT_NAMES = re.compile(v, flags=re.I | re.S) if v is not None else None
    if MDNS_REJECT_NAMES is not None:
        dbg(f"Names NOT resolved via Avahi: {MDNS_REJECT_NAMES.pattern}")

    v = os.environ.get("MDNS_ACCEPT_NAMES", None)
    MDNS_ACCEPT_NAMES = re.compile(v, flags=re.I | re.S) if v is not None else None
    if MDNS_ACCEPT_NAMES is not None:
        dbg(
            f"ONLY resolving the following names via Avahi: {MDNS_ACCEPT_NAMES.pattern}"
        )

    v = os.environ.get("MDNS_TIMEOUT", None)
    MDNS_TIMEOUT = int(v) if v is not None else None
    if MDNS_TIMEOUT is not None:
        dbg(f"Avahi request timeout: {MDNS_TIMEOUT}")

    MDNS_GETONE = str2bool(os.environ.get("MDNS_GETONE", str(True)))
    dbg(f"Terminate Avahi requests on first record: {MDNS_GETONE}")

    dbus_thread = threading.Thread(target=dbus_main)
    dbus_thread.daemon = True
    dbus_thread.start()


def deinit(*args, **kwargs) -> bool:
    dbus_loop.quit()
    dbus_thread.join()
    return True


def inform_super(id, qstate, superqstate, qdata) -> bool:
    return True


MODULE_EVENT_NEW: int
MODULE_EVENT_PASS: int
MODULE_WAIT_MODULE: int
MODULE_EVENT_MODDONE: int
MODULE_ERROR: int
MODULE_FINISHED: int
PKT_QR: int
PKT_RD: int
PKT_RA: int
DNSMessage: Callable


def get_rcode(msg) -> Rcode:
    if not msg:
        return Rcode.SERVFAIL

    return Rcode(msg.rep.flags & 0xF)


def rr2text(rec: tuple[str, RdataClass, RdataType, bytes], ttl: int) -> str:
    name, class_, type_, rdata = rec
    wire = array.array("B", rdata).tobytes()
    return f"{name}. {ttl} {dns.rdataclass.to_text(class_)} {dns.rdatatype.to_text(type_)} {dns.rdata.from_wire(class_, type_, wire, 0, len(wire), None)}"


def operate(id, event, qstate, qdata) -> bool:
    global NFT_QUERIES, NFT_TOKEN

    qi = qstate.qinfo
    name: str = qi.qname_str
    type_: RdataType = qi.qtype
    type_str: str = dns.rdatatype.to_text(type_)
    class_: RdataClass = qi.qclass
    class_str: str = dns.rdataclass.to_text(class_)
    rc: Rcode = get_rcode(qstate.return_msg)

    n2: str = name.rstrip(".")

    if event == MODULE_EVENT_NEW or event == MODULE_EVENT_PASS:
        qstate.ext_state[id] = MODULE_WAIT_MODULE
        return True

    if event != MODULE_EVENT_MODDONE:
        log_err("avahi-resolver: Unexpected event %d" % event)
        qstate.ext_state[id] = MODULE_ERROR
        return True

    qstate.ext_state[id] = MODULE_FINISHED

    # Only resolve via Avahi if we got NXDOMAIN from the upstream DNS
    # server, or if we could not reach the upstream DNS server. If we
    # got some records for the name from the upstream DNS server
    # already, do not resolve the record in Avahi.
    if rc != Rcode.NXDOMAIN and rc != Rcode.SERVFAIL:
        return True

    dbg(f"Got request for '{name} {class_str} {type_str}'")

    # Avahi only supports the IN class
    if class_ != RdataClass.IN:
        dbg("Rejected, Avahi only supports the IN class")
        return True

    # Avahi does not support meta queries (e.g., ANY)
    if dns.rdatatype.is_metatype(type_):
        dbg(f"Rejected, Avahi does not support the type {type_str}")
        return True

    # If we have a type blacklist and the requested type is on the
    # list, reject it.
    if MDNS_REJECT_TYPES and type_ in MDNS_REJECT_TYPES:
        dbg(f"Rejected, type {type_str} is on the blacklist")
        return True

    # If we have a type whitelist and if the requested type is not on
    # the list, reject it.
    if MDNS_ACCEPT_TYPES and type_ not in MDNS_ACCEPT_TYPES:
        dbg(f"Rejected, type {type_str} is not on the whitelist")
        return True

    # If we have a name blacklist and if the requested name matches
    # the blacklist, reject it.
    if MDNS_REJECT_NAMES is not None:
        if MDNS_REJECT_NAMES.search(name):
            dbg(f"Rejected, name {name} is on the blacklist")
            return True

    # If we have a name whitelist and if the requested name does not
    # match the whitelist, reject it.
    if MDNS_ACCEPT_NAMES is not None:
        if not MDNS_ACCEPT_NAMES.search(name):
            dbg(f"Rejected, name {name} is not on the whitelist")
            return True

    dbg(f"Resolving '{name} {class_str} {type_str}' via Avahi")

    recs = resolve(name, type_, getone=MDNS_GETONE, timeout=MDNS_TIMEOUT)

    if not recs:
        dbg("Result: Not found (NXDOMAIN)")
        qstate.return_rcode = Rcode.NXDOMAIN
        return True

    m = DNSMessage(name, type_, class_, PKT_QR | PKT_RD | PKT_RA)
    for r in recs:
        s = rr2text(r, MDNS_TTL)
        dbg(f"Result: {s}")
        m.answer.append(s)

    if not m.set_return_msg(qstate):
        raise Exception("Error in set_return_msg")

    qstate.return_msg.rep.security = 2

    if not storeQueryInCache(qstate, qstate.return_msg.qinfo, qstate.return_msg.rep, 0):
        raise Exception("Error in storeQueryInCache")

    qstate.return_rcode = Rcode.NOERROR
    return True


#
# It does not appear to be sufficient to check __name__ to determine
# whether we are being run in interactive mode. As a workaround, try
# to import module unboundmodule and if that fails, assume we're being
# run in interactive mode.
#
try:
    import unboundmodule  # type: ignore

    embedded = True
except ImportError:
    embedded = False

if __name__ == "__main__" and not embedded:
    import sys

    def log_info(msg):
        print(msg)

    def log_err(msg):
        print(f"ERROR: {msg}", file=sys.stderr)

    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <name> <rr_type>")
        sys.exit(2)

    name = sys.argv[1]
    type_str = sys.argv[2]

    try:
        type_: RdataType = dns.rdatatype.from_text(type_str)
    except dns.rdatatype.UnknownRdatatype:
        log_err(f'Unsupported DNS record type "{type_str}"')
        sys.exit(2)

    if dns.rdatatype.is_metatype(type_):
        log_err(f'Meta record type "{type_str}" cannot be resolved via Avahi')
        sys.exit(2)

    init()
    try:
        recs = resolve(name, type_, getone=MDNS_GETONE, timeout=MDNS_TIMEOUT)
        if not len(recs):
            print(f"{name} not found (NXDOMAIN)")
            sys.exit(1)

        for r in recs:
            print(rr2text(r, MDNS_TTL))
    finally:
        deinit()
