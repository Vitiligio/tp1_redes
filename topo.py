from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, Controller
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel

class CustomTopo(Topo):
    def build(self):
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')

        self.addLink(h1, s1)
        self.addLink(s1, s2, cls=TCLink, loss=10)
        self.addLink(s2, s3)
        self.addLink(s3, h2)

if __name__ == '__main__':
    setLogLevel('info')

    net = Mininet(topo=CustomTopo(), controller=Controller, link=TCLink)
    net.start()
    CLI(net)
    net.stop()
