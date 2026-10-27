import socket

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.lib.packet import ethernet, packet, udp
from ryu.ofproto import ofproto_v1_3

CONTROL_PORT = 5001
SERVICE_PORT = 7000
FILTER_TABLE = 0
FORWARD_TABLE = 1
CONTROL_PRIORITY = 100
ALLOW_PRIORITY = 60
DENY_PRIORITY = 50


class ServiceDiscoveryController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ServiceDiscoveryController, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.mac_to_port = {}
        self.allowed = set()
        self.last_counts = {}
        hub.spawn(self.monitor)

    def add_flow(self, dp, table, priority, match, actions=None, goto=None, idle=0):
        parser = dp.ofproto_parser
        ofp = dp.ofproto
        instructions = []
        if actions:
            instructions.append(parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions))
        if goto is not None:
            instructions.append(parser.OFPInstructionGotoTable(goto))
        dp.send_msg(parser.OFPFlowMod(datapath=dp, table_id=table, priority=priority,
                                      match=match, instructions=instructions, idle_timeout=idle))

    def service_match(self, parser, ip=None):
        if ip is None:
            return parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=SERVICE_PORT)
        return parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=SERVICE_PORT, ipv4_dst=ip)

    def allow(self, dp, ip):
        match = self.service_match(dp.ofproto_parser, ip)
        self.add_flow(dp, FILTER_TABLE, ALLOW_PRIORITY, match, goto=FORWARD_TABLE)

    def block(self, dp, ip):
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        match = self.service_match(parser, ip)
        dp.send_msg(parser.OFPFlowMod(datapath=dp, table_id=FILTER_TABLE, command=ofp.OFPFC_DELETE_STRICT,
                                      priority=ALLOW_PRIORITY, match=match,
                                      out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def on_switch_ready(self, ev):
        dp = ev.msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        self.datapaths[dp.id] = dp
        self.mac_to_port[dp.id] = {}
        dp.send_msg(parser.OFPFlowMod(datapath=dp, table_id=ofp.OFPTT_ALL, command=ofp.OFPFC_DELETE,
                                      out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
                                      match=parser.OFPMatch()))
        to_controller = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self.add_flow(dp, FILTER_TABLE, 0, parser.OFPMatch(), goto=FORWARD_TABLE)
        self.add_flow(dp, FORWARD_TABLE, 0, parser.OFPMatch(), actions=to_controller)
        control_match = parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=CONTROL_PORT)
        self.add_flow(dp, FILTER_TABLE, CONTROL_PRIORITY, control_match, actions=to_controller)
        self.add_flow(dp, FILTER_TABLE, DENY_PRIORITY, self.service_match(parser))
        for ip in self.allowed:
            self.allow(dp, ip)
        self.logger.info("switch s%s connected", dp.id)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def on_state_change(self, ev):
        dp = ev.datapath
        if ev.state == DEAD_DISPATCHER and dp.id in self.datapaths:
            del self.datapaths[dp.id]

    def handle_control(self, pkt):
        raw = None
        for p in pkt.protocols:
            if isinstance(p, (bytes, bytearray)):
                raw = bytes(p)
        if raw is None:
            return
        text = raw.decode("ascii", errors="ignore").replace("\x00", " ")
        parts = text.split()
        if len(parts) != 2:
            return
        action = parts[0].upper()
        ip = parts[1]
        try:
            socket.inet_aton(ip)
        except OSError:
            return
        if action == "ALLOW" and ip not in self.allowed:
            self.allowed.add(ip)
            for dp in list(self.datapaths.values()):
                self.allow(dp, ip)
            self.logger.info("ALLOW service traffic to %s", ip)
        elif action == "BLOCK" and ip in self.allowed:
            self.allowed.discard(ip)
            for dp in list(self.datapaths.values()):
                self.block(dp, ip)
            self.logger.info("BLOCK service traffic to %s", ip)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def on_packet_in(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype == 0x88cc:
            return

        u = pkt.get_protocol(udp.udp)
        if u is not None and u.dst_port == CONTROL_PORT:
            self.handle_control(pkt)
            return

        table = self.mac_to_port.setdefault(dp.id, {})
        table[eth.src] = in_port
        out_port = table.get(eth.dst, ofp.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]
        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst, eth_src=eth.src)
            self.add_flow(dp, FORWARD_TABLE, 1, match, actions=actions, idle=60)
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
                                        actions=actions, data=msg.data))

    def monitor(self):
        while True:
            hub.sleep(5)
            for dp in list(self.datapaths.values()):
                dp.send_msg(dp.ofproto_parser.OFPFlowStatsRequest(dp, table_id=FILTER_TABLE))

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def on_flow_stats(self, ev):
        dp = ev.msg.datapath
        for stat in ev.msg.body:
            if stat.priority == ALLOW_PRIORITY:
                label = "allowed to %s" % stat.match["ipv4_dst"]
            elif stat.priority == DENY_PRIORITY:
                label = "dropped (not registered)"
            else:
                continue
            key = (dp.id, stat.priority, label)
            if self.last_counts.get(key) != stat.packet_count:
                self.last_counts[key] = stat.packet_count
                self.logger.info("STATS s%s service traffic %s: %d packets, %d bytes",
                                 dp.id, label, stat.packet_count, stat.byte_count)
