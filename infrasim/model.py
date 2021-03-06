#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Author:  Robert Xia <robert.xia@emc.com>,
# Forrest Gu <Forrest.Gu@emc.com>

"""
This module majorly defines infrasim element models.
For each element class, they need to implement methods:

    - __init__()
        Get initialized with element information;
        Define element attributes;
        Assign default value for certain attributes;
    - init()
        Parse information dict, assign to all attribute;
    - precheck()
        Validate attribute integrity and environment compatibility;
    - handle_params()
        Add all attributes to command line options list;
    - get_option()
        Compose all options in list to a command line string;
"""

import fcntl
import time
import shlex
import subprocess
import os
import uuid
import signal
import jinja2
import netifaces
import math
import yaml
import shutil
import stat
from . import logger, run_command, CommandRunFailed, ArgsNotCorrect, CommandNotFound, has_option

TEMPLATE_ROOT = "/usr/local/etc/infrasim"


class Utility(object):
    @staticmethod
    def execute_command(command, log_path=""):
        args = shlex.split(command)
        proc = subprocess.Popen(args, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                shell=False)

        flags = fcntl.fcntl(proc.stderr, fcntl.F_GETFL)
        fcntl.fcntl(proc.stderr, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        time.sleep(1)

        errout = None
        try:
            errout = proc.stderr.read()
        except IOError:
            pass
        if errout is not None:
            if log_path:
                with open(log_path, 'w') as fp:
                    fp.write(errout)
            else:
                logger.error(errout)

        if not os.path.isdir("/proc/{}".format(proc.pid)):
            raise CommandRunFailed(command)

        return proc.pid

    @staticmethod
    def run_command(command):
        args = shlex.split(command)
        command_output = subprocess.check_output(args, shell=False)
        return command_output

    @staticmethod
    def get_working_directory():
        return os.path.dirname(os.path.abspath(__file__))

    @staticmethod
    def ping_status(ip):
        rtn = True
        st = subprocess.call(['ping -c 3 %s >/dev/null' % ip], shell=True)
        if st:
            rtn = False
        return rtn


class CElement(object):
    def __init__(self):
        self.__option_list = []

    def precheck(self):
        raise NotImplementedError("precheck is not implemented")

    def init(self):
        raise NotImplementedError("init is not implemented")

    def handle_parms(self):
        raise NotImplementedError("handle_parms is not implemented")

    def add_option(self, option):
        if option is None:
            return

        if option in self.__option_list:
            print "Warning: option {} already added.".format(option)
            return

        self.__option_list.append(option)

    def get_option(self):
        if len(self.__option_list) == 0:
            raise Exception("No option in the list")

        return " ".join(self.__option_list)


class CCPU(CElement):
    def __init__(self, cpu_info, socket_in_smbios=None):
        super(CCPU, self).__init__()
        self.__cpu = cpu_info
        self.__type = "host"
        self.__features = "+vmx"
        self.__quantities = 2
        self.__socket = socket_in_smbios

    def get_cpu_quantities(self):
        return self.__quantities

    def precheck(self):
        """
        Check if the CPU quantities exceeds the real physical CPU cores
        """
        if self.__quantities <= 0:
            raise ArgsNotCorrect(
                '[model:cpu] quantities invalid: {}, should be positive'.
                format(self.__quantities))

        if self.__quantities % self.__socket != 0:
            raise ArgsNotCorrect(
                '[model:cpu] quantities: {} is not divided by socket: {}'.
                format(self.__quantities, self.__socket))

    def init(self):
        if 'type' in self.__cpu:
            self.__type = self.__cpu['type']

        if 'quantities' in self.__cpu:
            self.__quantities = self.__cpu['quantities']

        if 'features' in self.__cpu:
            self.__features = self.__cpu['features']

        if self.__socket is None:
            self.__socket = 2

    def handle_parms(self):
        if self.__features:
            cpu_option = "-cpu {0},{1}".format(self.__type, self.__features)
        else:
            cpu_option = "-cpu {}".format(self.__type)

        self.add_option(cpu_option)

        cores = self.__quantities / self.__socket
        smp_option = "-smp {vcpu_num},sockets={socket},cores={cores},threads=1".format(
                vcpu_num=self.__quantities, socket=self.__socket, cores=cores)

        self.add_option(smp_option)


class CMemory(CElement):
    def __init__(self, memory_info):
        super(CMemory, self).__init__()
        self.__memory = memory_info
        self.__memory_size = None

    def precheck(self):
        """
        Check if the memory size exceeds the system available size
        """
        pass

    def init(self):
        if 'size' in self.__memory:
            self.__memory_size = self.__memory['size']
        else:
            raise Exception("ERROR: please set the memory size")

    def handle_parms(self):
        memory_option = "-m {}".format(self.__memory_size)
        self.add_option(memory_option)


class CDrive(CElement):
    def __init__(self, drive_info):
        super(CDrive, self).__init__()
        self.__drive = drive_info
        self.__index = None
        self.__vendor = None
        self.__model = None
        self.__serial = None
        self.__product = None
        self.__version = None
        self.__bootindex = None
        self.__cache = "writeback"  # none/writeback/writethrough
        self.__aio = None  # threads/native
        self.__file = None
        self.__rotation = None
        self.__type = "file"
        self.__format = "qcow2"
        self.__bus_address = None
        self.__size = 8
        self.__controller_type = None

    def set_index(self, index):
        self.__index = index

    def get_index(self):
        return self.__index

    def set_bus(self, addr):
        self.__bus_address = addr

    def set_controller_type(self, controller_type):
        self.__controller_type = controller_type

    def get_controller_type(self):
        return self.__controller_type

    def precheck(self):
        """
        Check if the parition or drive file exists
        Check if the cache/aio parameters are valid
        """
        pass

    def init(self):
        if 'bootindex' in self.__drive:
            self.__bootindex = self.__drive['bootindex']

        # for ide-hd drive, there is no vendor properties
        if self.__controller_type == "megasas" or \
                self.__controller_type == "megasas-gen2":
            self.__vendor = self.__drive['vendor'] if \
                'vendor' in self.__drive else None

        if self.__controller_type == "ahci":
            self.__model = self.__drive['model'] if \
                'model' in self.__drive else None

        if 'serial' in self.__drive:
            self.__serial = self.__drive['serial']

        if 'model' in self.__drive:
            self.__model = self.__drive['model']

        if 'product' in self.__drive:
            self.__product = self.__drive['product']

        if 'version' in self.__drive:
            self.__version = self.__drive['version']

        if 'rotation' in self.__drive:
            self.__rotation = self.__drive['rotation']

        if 'format' in self.__drive:
            self.__format = self.__drive['format']

        if 'cache' in self.__drive:
            self.__cache = self.__drive['cache']

        if 'aio' in self.__drive:
            self.__aio = self.__drive['aio']

        if 'size' in self.__drive:
            self.__size = self.__drive['size']

        # If user announce drive file in config, use it
        # else create for them.
        if 'file' in self.__drive:
            self.__file = self.__drive['file']
            # assume the files starts with "/dev/" are block device
            # all the block devices are assumed to be raw format
            if self.__file.startswith("/dev/"):
                self.__format = "raw"
        else:
            disk_file_base = os.environ['HOME'] + '/.infrasim/'
            disk_file = disk_file_base + "sd{0}.img".format(chr(97+self.__index))
            if not os.path.exists(disk_file):
                command = "qemu-img create -f qcow2 {0}sd{1}.img {2}G".\
                    format(disk_file_base, chr(97+self.__index), self.__size)
                try:
                    run_command(command)
                except CommandRunFailed as e:
                    raise e
            self.__file = disk_file

    def handle_parms(self):
        host_option = ""
        if self.__file:
            host_option = "file={}".format(self.__file)
        else:
            raise Exception("Please specify the file option for disk.")

        if self.__format:
            host_option = ",".join([host_option, "format={}".format(self.__format)])

        if self.__controller_type == "ahci":
            prefix = "sata"
        else:
            prefix = "scsi"

        host_option = ",".join([host_option, "if={}".format("none")])
        host_option = ",".join([host_option, "id=drive{}".format(self.__index)])

        if self.__cache:
            host_option = ",".join([host_option, "cache={}".format(self.__cache)])

        if self.__aio and self.__cache == "none":
            host_option = ",".join([host_option, "aio={}".format(self.__aio)])

        device_option = ""

        if self.__controller_type == "ahci":
            device_option = "ide-hd"
        elif self.__controller_type.startswith("megasas") or \
                self.__controller_type.startswith("lsi"):
            device_option = "scsi-hd"
        else:
            device_option = "ide-hd"

        if self.__vendor:
            device_option = ",".join([device_option, "vendor={}".format(self.__vendor)])

        if self.__model:
            device_option = ",".join([device_option, "model={}".format(self.__model)])

        if self.__product:
            device_option = ",".join([device_option, "product={}".format(self.__product)])

        if self.__serial:
            device_option = ",".join([device_option, "serial={}".format(self.__serial)])

        if self.__version:
            device_option = ",".join([device_option, "ver={}".format(self.__version)])

        if self.__bootindex:
            device_option = ",".join([device_option, "bootindex={}".format(self.__bootindex)])

        if self.__rotation is not None:
            device_option = ",".join([device_option, "rotation={}".format(self.__rotation)])

        if self.__bus_address:
            device_option = ",".join([device_option, "bus={}".format(self.__bus_address)])

        device_option = ",".join([device_option, "drive=drive{}".format(self.__index)])

        drive_option = " ".join(["-drive", host_option,
                                "-device", device_option])

        self.add_option(drive_option)


class CStorageController(CElement):
    def __init__(self, controller_info):
        super(CStorageController, self).__init__()
        self.__controller_info = controller_info
        self.__max_drive_per_controller = None
        self.__controller_type = None
        self.__drive_list = []
        # Only used for raid controller (megasas)
        self.__use_jbod = None

    def precheck(self):
        # Check controller params

        # check each drive params
        for drive_obj in self.__drive_list:
            drive_obj.precheck()

    def init(self):
        self.__max_drive_per_controller = \
            self.__controller_info['controller']['max_drive_per_controller']
        self.__controller_type = self.__controller_info['controller']['type']

        if self.__controller_type == "ahci":
            prefix = "sata"
        else:
            prefix = "scsi"

        if 'use_jbod' in self.__controller_info['controller'] and \
                (self.__controller_type == "megasas" or
                    self.__controller_type == "megasas-gen2"):
            self.__use_jbod = self.__controller_info['controller']['use_jbod']

        drive_index = 0
        controller_index = 0
        for drive_info in self.__controller_info['controller']['drives']:
            drive_obj = CDrive(drive_info)
            drive_obj.set_index(drive_index)
            if drive_index > self.__max_drive_per_controller - 1:
                controller_index += 1
            drive_obj.set_controller_type(self.__controller_type)
            if self.__controller_type == "ahci":
                unit = drive_index
            else:
                unit = 0
            drive_obj.set_bus("{}{}.{}".format(prefix, controller_index, unit))
            self.__drive_list.append(drive_obj)
            drive_index += 1

        for drive_obj in self.__drive_list:
            drive_obj.init()

    def handle_params(self):
        controller_option_list = []
        drive_quantities = \
            len(self.__controller_info['controller']['drives'])
        controller_quantities = \
            int(math.ceil(float(drive_quantities)
                / self.__max_drive_per_controller))
        if self.__controller_type == "ahci":
            prefix = "sata"
        else:
            prefix = "scsi"

        for controller_index in range(0, controller_quantities):
            controller_option_list.append(
                "-device {}".format(
                    self.__controller_info['controller']['type']))
            controller_option_list.append(
                "id={}{}".format(prefix, controller_index))
            if self.__use_jbod is not None:
                controller_option_list.append(
                    "use_jbod={}".format(self.__use_jbod))
            self.add_option("{}".format(",".join(controller_option_list)))

        for drive_obj in self.__drive_list:
            drive_obj.handle_parms()

        for drive_obj in self.__drive_list:
            self.add_option(drive_obj.get_option())


class CBackendStorage(CElement):
    def __init__(self, backend_storage_info):
        super(CBackendStorage, self).__init__()
        self.__backend_storage_info = backend_storage_info
        self.__controller_list = []

    def precheck(self):
        for controller_obj in self.__controller_list:
            controller_obj.precheck()

    def init(self):
        for controller in self.__backend_storage_info:
            controller_obj = CStorageController(controller)
            self.__controller_list.append(controller_obj)

        for controller_obj in self.__controller_list:
            controller_obj.init()

    def handle_parms(self):
        for controller_obj in self.__controller_list:
            controller_obj.handle_params()

        for controller_obj in self.__controller_list:
            self.add_option(controller_obj.get_option())


class CNetwork(CElement):
    def __init__(self, network_info):
        super(CNetwork, self).__init__()
        self.__network = network_info
        self.__network_list = []
        self.__network_mode = "nat"
        self.__bridge_name = None
        self.__nic_name = None
        self.__mac_address = None
        self.__index = 0

    def set_index(self, index):
        self.__index = index

    def precheck(self):
        # Check if parameters are valid
        # bridge exists?
        pass

    def init(self):
        if 'network_mode' in self.__network:
            self.__network_mode = self.__network['network_mode']

        if 'network_name' in self.__network:
            self.__bridge_name = self.__network['network_name']

        if 'device' in self.__network:
            self.__nic_name = self.__network['device']

        if 'mac' in self.__network:
            self.__mac_address = self.__network['mac']

    def handle_parms(self):
        if self.__mac_address is None:
            uuid_val = uuid.uuid4()
            str1 = str(uuid_val)[-2:]
            str2 = str(uuid_val)[-4:-2]
            str3 = str(uuid_val)[-6:-4]
            self.__mac_address = ":".join(["52:54:BE", str1, str2, str3])

        if self.__network_mode == "bridge":
            if self.__bridge_name is None:
                self.__bridge_name = "br0"

            netdev_option = ",".join(['bridge', 'id=netdev{}'.format(self.__index),
                                      'br={}'.format(self.__bridge_name),
                                      'helper=/usr/libexec/qemu-bridge-helper'])
            nic_option = ",".join(["{}".format(self.__nic_name),
                                   "netdev=netdev{}".format(self.__index),
                                   "mac={}".format(self.__mac_address)])

            network_option = " ".join(["-netdev {}".format(netdev_option),
                                       "-device {}".format(nic_option)])
        elif self.__network_mode == "nat":
            network_option = "-net user -net nic"
        else:
            raise Exception("ERROR: {} is not supported now.".
                            format(self.__network_mode))

        self.add_option(network_option)


class CBackendNetwork(CElement):
    def __init__(self, network_info_list):
        super(CBackendNetwork, self).__init__()
        self.__backend_network_list = network_info_list

        self.__network_list = []

    def precheck(self):
        for network_obj in self.__network_list:
            network_obj.precheck()

    def init(self):
        index = 0
        for network in self.__backend_network_list:
            network_obj = CNetwork(network)
            network_obj.set_index(index)
            self.__network_list.append(network_obj)
            index += 1

        for network_obj in self.__network_list:
            network_obj.init()

    def handle_parms(self):
        for network_obj in self.__network_list:
            network_obj.handle_parms()

        for network_obj in self.__network_list:
            self.add_option(network_obj.get_option())


class CIPMI(CElement):
    def __init__(self, ipmi_info):
        super(CIPMI, self).__init__()
        self.__ipmi = ipmi_info
        self.__interface = None
        self.__host = None
        self.__bmc_connection_port = None

    def precheck(self):
        """
        Check if internal socket port is used.
        """
        pass

    def init(self):
        if 'interface' in self.__ipmi:
            self.__interface = self.__ipmi['interface']

        if 'host' in self.__ipmi:
            self.__host = self.__ipmi['host']

        if 'bmc_connection_port' in self.__ipmi:
            self.__bmc_connection_port = self.__ipmi['bmc_connection_port']

    def handle_parms(self):
        chardev_option = ','.join(["socket", 'id=ipmi0',
                                   'host={}'.format(self.__host),
                                   'port={}'.
                                  format(self.__bmc_connection_port),
                                   'reconnect=10'])
        bmc_option = ','.join(['ipmi-bmc-extern', 'chardev=ipmi0', 'id=bmc0'])
        interface_option = ','.join(['isa-ipmi-kcs', 'bmc=bmc0'])

        ipmi_option = " ".join(["-chardev {}".format(chardev_option),
                                "-device {}".format(bmc_option),
                                "-device {}".format(interface_option)])
        self.add_option(ipmi_option)


class Task(object):
    def __init__(self):
        # priroty should be range from 0 to 5
        # +-----+-----+-----+----+-----+
        # |  0  |  1  |  2  |  3 |  4  |
        # +-----+-----+-----+----+-----+
        # |High |                | Low |
        # +-----+-----+-----+----+-----+
        self.__task_priority = None
        self.__workspace = ""
        self.__task_name = None
        self.__debug = False
        self.__log_path = ""

        # If any task set the __run_mask to True,
        # this task shall only be maintained with information
        # no actual run shall be taken
        self.__run_mask = False

    def set_priority(self, priority):
        self.__task_priority = priority

    def get_priority(self):
        return self.__task_priority

    def set_task_name(self, name):
        self.__task_name = name

    def get_task_name(self):
        return self.__task_name

    def get_commandline(self):
        raise NotImplementedError("get_commandline not implemented")

    def set_workspace(self, directory):
        self.__workspace = directory

    def get_workspace(self):
        return self.__workspace

    def set_log_path(self, log_path):
        self.__log_path = log_path

    def set_run_mask(self, run_mask):
        self.__run_mask = run_mask

    def get_task_pid(self):
        pid_file = "{}/.{}".format(self.__workspace, self.__task_name)
        try:
            with open(pid_file, "r") as f:
                pid = f.readline()
        except Exception, e:
            return None
        return pid.strip()

    def run(self):
        if self.__run_mask:
            start = time.time()
            while True:
                pid = self.get_task_pid()
                if pid is not None:
                    break
                if time.time()-start > 5:
                    break
            if pid is None:
                print "[ {:<6} ] {} fail to start".\
                    format(pid, self.__task_name)
            else:
                print "[ {:<6} ] {} run".format(pid, self.__task_name)
            return

        if self.__debug:
            print self.get_commandline()
            return

        pid = self.get_task_pid()
        if pid > 0:
            if os.path.exists("/proc/{}".format(pid)):
                print "[ {:<6} ] {} is already running".\
                    format(pid, self.__task_name)
                return
            else:
                os.remove("{}/.{}".format(self.__workspace, self.__task_name))

        pid = Utility.execute_command(self.get_commandline(),
                                      log_path=self.__log_path)
        print "[ {:<6} ] {} start to run".format(pid, self.__task_name)
        pid_file = "{}/.{}".format(self.__workspace, self.__task_name)
        with open(pid_file, "w") as f:
            f.write("{}".format(pid))

    def terminate(self):
        task_pid = self.get_task_pid()
        pid_file = "{}/.{}".format(self.__workspace, self.__task_name)
        try:
            if task_pid:
                print "[ {:<6} ] {} stop".format(task_pid, self.__task_name)
                os.kill(int(task_pid), signal.SIGTERM)
                time.sleep(1)
                if os.path.exists(pid_file):
                    os.remove(pid_file)
        except OSError:
            if os.path.exists(pid_file):
                os.remove(pid_file)
            if not os.path.exists("/proc/{}".format(task_pid)):
                pass
            else:
                print("[ {:<6} ] {} stop failed.".
                      format(task_pid, self.__task_name))

    def status(self):
        task_pid = self.get_task_pid()
        pid_file = "{}/.{}".format(self.__workspace, self.__task_name)
        if not os.path.exists(pid_file):
            print("{} is stopped".format(self.__task_name))
        elif not os.path.exists("/proc/{}".format(task_pid)):
            print("{} is stopped".format(self.__task_name))
            os.remove(pid_file)
        else:
            task_pid = self.get_task_pid()
            if task_pid:
                print "[ {:<6} ] {} is running".\
                    format(task_pid, self.__task_name)


class CCompute(Task, CElement):
    def __init__(self, compute_info):
        super(CCompute, self).__init__()
        CElement.__init__(self)
        self.__compute = compute_info
        self.__element_list = []
        self.__enable_kvm = True
        self.__smbios = None
        self.__bios = None
        self.__boot_order = "ncd"
        self.__qemu_bin = "qemu-system-x86_64"
        self.__cdrom_file = None
        self.__vendor_type = None
        # remember cpu object
        self.__cpu_obj = None
        self.__numactl_obj = None

        # Node wise attributes
        self.__port_qemu_ipmi = 9002
        self.__port_serial = 9003

    def set_numactl(self, numactl_obj):
        self.__numactl_obj = numactl_obj

    def set_type(self, vendor_type):
        self.__vendor_type = vendor_type

    def set_port_qemu_ipmi(self, port):
        self.__port_qemu_ipmi = port

    def set_port_serial(self, port):
        self.__port_serial = port

    def set_smbios(self, smbios):
        self.__smbios = smbios

    def get_smbios(self):
        return self.__smbios

    def precheck(self):
        # check if qemu-system-x86_64 exists
        try:
            run_command("which {}".format(self.__qemu_bin))
        except CommandRunFailed:
            raise CommandNotFound(self.__qemu_bin)

        # check if smbios exists
        if not os.path.isfile(self.__smbios):
            raise ArgsNotCorrect("Target SMBIOS file doesn't exist: {}".
                                 format(self.__smbios))

        # check sub-elements
        for element in self.__element_list:
            element.precheck()

    def init(self):

        if 'kvm_enabled' in self.__compute:
            if self.__compute['kvm_enabled']:
                if os.path.exists("/dev/kvm"):
                    self.__enable_kvm = True
                    logger.info('[model:compute] infrasim has enabled kvm')
                else:
                    self.__enable_kvm = False
                    logger.warning('[model:compute] infrasim can\'t '
                                   'enable kvm on this environment')
            else:
                self.__enable_kvm = False
                logger.info('[model:compute] infrasim doesn\'t enable kvm')

        if 'smbios' in self.__compute:
            self.__smbios = self.__compute['smbios']
        elif self.get_workspace():
            self.__smbios = os.path.join(self.get_workspace(),
                                         "data",
                                         "{}_smbios.bin".
                                         format(self.__vendor_type))
        else:
            self.__smbios = "/usr/local/etc/infrasim/{0}/{0}_smbios.bin".\
                format(self.__vendor_type)

        if 'bios' in self.__compute:
            self.__bios = self.__compute['bios']

        if 'boot_order' in self.__compute:
            self.__boot_order = self.__compute['boot_order']

        if 'cdrom' in self.__compute:
            self.__cdrom_file = self.__compute['cdrom']

        if 'numa_control' in self.__compute \
                and self.__compute['numa_control']:
            if os.path.exists("/usr/bin/numactl"):
                self.set_numactl(NumaCtl())
                logger.info('[model:compute] infrasim has '
                           'enabled numa control')
            else:
                logger.info('[model:compute] infrasim can\'t '
                           'find numactl in this environment')

        cpu_obj = CCPU(self.__compute['cpu'])
        self.__element_list.append(cpu_obj)
        self.__cpu_obj = cpu_obj

        memory_obj = CMemory(self.__compute['memory'])
        self.__element_list.append(memory_obj)

        backend_storage_obj = \
            CBackendStorage(self.__compute['storage_backend'])
        self.__element_list.append(backend_storage_obj)

        backend_network_obj = CBackendNetwork(self.__compute['networks'])
        self.__element_list.append(backend_network_obj)

        if has_option(self.__compute, "ipmi"):
            ipmi_obj = CIPMI({
                "interface": self.__compute["ipmi"].get("interface", "kcs"),
                "host": self.__compute["ipmi"].get("host", "127.0.0.1"),
                "bmc_connection_port": self.__port_qemu_ipmi
            })
        else:
            ipmi_obj = CIPMI({
                "interface": "kcs",
                "host": "127.0.0.1",
                "bmc_connection_port": self.__port_qemu_ipmi
            })

        self.__element_list.append(ipmi_obj)

        for element in self.__element_list:
            element.init()

    def get_commandline(self):
        # handle params
        self.handle_parms()

        qemu_commandline = ""
        for element_obj in self.__element_list:
            qemu_commandline = " ".join([element_obj.get_option(), qemu_commandline])

        qemu_commandline = " ".join([self.__qemu_bin, self.get_option(), qemu_commandline])

        # set cpu affinity
        if self.__numactl_obj:
            cpu_number = self.__cpu_obj.get_cpu_quantities()
            bind_cpu_list = [str(x) for x in self.__numactl_obj.get_cpu_list(cpu_number)]
            if len(bind_cpu_list) > 0:
                numactl_option = 'numactl --physcpubind={} --localalloc'.format(','.join(bind_cpu_list))
                qemu_commandline = " ".join([numactl_option, qemu_commandline])

        return qemu_commandline

    def handle_parms(self):
        self.add_option("-vnc :1")
        self.add_option("-name {}".format(self.get_task_name()))
        self.add_option("-device sga")

        if self.__enable_kvm:
            self.add_option("--enable-kvm")

        if self.__smbios:
            self.add_option("-smbios file={}".format(self.__smbios))

        if self.__bios:
            self.add_option("-bios {}".format(self.__bios))

        if self.__boot_order:
            self.add_option("-boot {}".format(self.__boot_order))

        self.add_option("-machine q35,usb=off,vmport=off")

        if self.__cdrom_file:
            self.add_option("-cdrom {}".format(self.__cdrom_file))

        self.add_option("-chardev socket,id=mon,host=127.0.0.1,"
                        "port=2345,server,nowait ")

        self.add_option("-mon chardev=mon,id=monitor")

        if self.__port_serial:
            self.add_option("-serial mon:udp:127.0.0.1:{},nowait".
                            format(self.__port_serial))

        self.add_option("-uuid {}".format(str(uuid.uuid4())))

        for element_obj in self.__element_list:
            element_obj.handle_parms()


class CBMC(Task):

    VBMC_TEMP_CONF = "/usr/local/etc/infrasim/conf/vbmc.conf"
    VBMC_CONF = "/etc/infrasim/vbmc.conf"

    def __init__(self, bmc_info={}):
        super(CBMC, self).__init__()

        self.__bmc = bmc_info
        self.__address = 0x20
        self.__channel = 1
        self.__lan_interface = None
        self.__lancontrol_script = ""
        self.__chassiscontrol_script = ""
        self.__startcmd_script = ""
        self.__startnow = "true"
        self.__poweroff_wait = 5
        self.__kill_wait = 1
        self.__username = "admin"
        self.__password = "admin"
        self.__emu_file = None
        self.__config_file = ""
        self.__bin = "/usr/local/bin/ipmi_sim"
        self.__port_iol = 623
        self.__historyfru = 10

        # Node wise attributes
        self.__vendor_type = None
        self.__port_ipmi_console = 9000
        self.__port_qemu_ipmi = 9002
        self.__sol_device = ""

    def set_type(self, vendor_type):
        self.__vendor_type = vendor_type

    def set_port_ipmi_console(self, port):
        self.__port_ipmi_console = port

    def set_port_qemu_ipmi(self, port):
        self.__port_qemu_ipmi = port

    def set_sol_device(self, device):
        self.__sol_device = device

    def get_config_file(self):
        return self.__config_file

    def set_config_file(self, dst):
        self.__config_file = dst

    def get_emu_file(self):
        return self.__emu_file

    def set_emu_file(self, path):
        self.__emu_file = path

    def set_startcmd_script(self, path):
        self.__startcmd_script = path

    def get_startcmd_script(self):
        return self.__startcmd_script

    def set_chassiscontrol_script(self, path):
        self.__chassiscontrol_script = path

    def get_chassiscontrol_script(self):
        return self.__chassiscontrol_script

    def set_lancontrol_script(self, path):
        self.__lancontrol_script = path

    def get_lancontrol_script(self):
        return self.__lancontrol_script

    def precheck(self):
        # check if ipmi_sim exists
        try:
            run_command("which {}".format(self.__bin))
        except CommandRunFailed:
            raise CommandNotFound(self.__bin)

        # check script exits
        if not os.path.exists(self.__lancontrol_script):
            raise ArgsNotCorrect("Lan control script {} doesn\'t exist".
                                 format(self.__lancontrol_script))

        if not os.path.exists(self.__chassiscontrol_script):
            raise ArgsNotCorrect("Chassis control script {} doesn\'t exist".
                                 format(self.__chassiscontrol_script))

        if not os.path.exists(self.__startcmd_script):
            raise ArgsNotCorrect("startcmd script {} doesn\'t exist".
                                 format(self.__chassiscontrol_script))

        # check ports are in use
        # check lan interface exists

        # check attribute
        if self.__poweroff_wait < 0:
            raise ArgsNotCorrect("poweroff_wait is expected to be >= 0, "
                                 "it's set to {} now".
                                 format(self.__poweroff_wait))

        if type(self.__poweroff_wait) is not int:
            raise ArgsNotCorrect("poweroff_wait is expected to be integer, "
                                 "it's set to {} now".
                                 format(self.__poweroff_wait))

        if self.__kill_wait < 0:
            raise ArgsNotCorrect("kill_wait is expected to be >= 0, "
                                 "it's set to {} now".
                                 format(self.__kill_wait))

        if type(self.__kill_wait) is not int:
            raise ArgsNotCorrect("kill_wait is expected to be integer, "
                                 "it's set to {} now".
                                 format(self.__kill_wait))

        if self.__port_iol < 0:
            raise ArgsNotCorrect("Port for IOL(IPMI over LAN) is expected "
                                 "to be >= 0, it's set to {} now".
                                 format(self.__port_iol))

        if type(self.__port_iol) is not int:
            raise ArgsNotCorrect("Port for IOL(IPMI over LAN) is expected "
                                 "to be integer, it's set to {} now".
                                 format(self.__port_iol))

        if self.__historyfru < 0:
            raise ArgsNotCorrect("History FRU is expected to be >= 0, "
                                 "it's set to {} now".
                                 format(self.__historyfru))

        if type(self.__historyfru) is not int:
            raise ArgsNotCorrect("History FRU is expected to be integer, "
                                 "it's set to {} now".
                                 format(self.__historyfru))

        # check configuration file exists
        if not os.path.isfile(self.__emu_file):
            raise ArgsNotCorrect("Target emulation file doesn't exist: {}".
                                 format(self.__emu_file))

        if not os.path.isfile(self.__config_file):
            raise ArgsNotCorrect("Target config file doesn't exist: {}".
                                 format(self.__config_file))

    def write_bmc_config(self, dst=None):
        if dst is None:
            dst = self.__config_file
        else:
            self.__config_file = dst

        # Render vbmc.conf
        bmc_conf = ""
        with open(self.__class__.VBMC_TEMP_CONF, "r") as f:
            bmc_conf = f.read()
        template = jinja2.Template(bmc_conf)
        bmc_conf = template.render(startcmd_script=self.__startcmd_script,
                                   chassis_control_script=self.__chassiscontrol_script,
                                   lan_control_script=self.__lancontrol_script,
                                   lan_interface=self.__lan_interface,
                                   username=self.__username,
                                   password=self.__password,
                                   port_qemu_ipmi=self.__port_qemu_ipmi,
                                   port_ipmi_console=self.__port_ipmi_console,
                                   port_iol=self.__port_iol,
                                   sol_device=self.__sol_device,
                                   poweroff_wait=self.__poweroff_wait,
                                   kill_wait=self.__kill_wait,
                                   startnow=self.__startnow,
                                   historyfru=self.__historyfru)

        with open(dst, "w") as f:
            f.write(bmc_conf)

    def init(self):
        if 'address' in self.__bmc:
            self.__address = self.__bmc['address']

        if 'channel' in self.__bmc:
            self.__channel = self.__bmc['channel']

        if 'interface' in self.__bmc:
            self.__lan_interface = self.__bmc['interface']
        else:
            nics_list = netifaces.interfaces()
            self.__lan_interface = filter(lambda x: 'e' in x, nics_list)[0]

        if 'lancontrol' in self.__bmc:
            self.__lancontrol_script = self.__bmc['lancontrol']
        elif self.get_workspace():
            self.__lancontrol_script = os.path.join(self.get_workspace(),
                                                    "script",
                                                    "lancontrol")
        else:
            self.__lancontrol_script \
                = "/usr/local/etc/infrasim/script/lancontrol"

        if 'chassiscontrol' in self.__bmc:
            self.__chassiscontrol_script = self.__bmc['chassiscontrol']
        elif self.get_workspace():
            self.__chassiscontrol_script = os.path.join(self.get_workspace(),
                                                        "script",
                                                        "chassiscontrol")

        if 'startcmd' in self.__bmc:
            self.__startcmd_script = self.__bmc['startcmd']
        elif self.get_workspace():
            self.__startcmd_script = os.path.join(self.get_workspace(),
                                                  "script",
                                                  "startcmd")

        if 'startnow' in self.__bmc:
            if self.__bmc['startnow']:
                self.__startnow = "true"
            else:
                self.__startnow = "false"

        if 'poweroff_wait' in self.__bmc:
            self.__poweroff_wait = self.__bmc['poweroff_wait']

        if 'kill_wait' in self.__bmc:
            self.__kill_wait = self.__bmc['kill_wait']

        if 'username' in self.__bmc:
            self.__username = self.__bmc['username']

        if 'password' in self.__bmc:
            self.__password = self.__bmc['password']

        if 'ipmi_over_lan_port' in self.__bmc:
            self.__port_iol = self.__bmc['ipmi_over_lan_port']

        if 'historyfru' in self.__bmc:
            self.__historyfru = self.__bmc['historyfru']

        if 'emu_file' in self.__bmc:
            self.__emu_file = self.__bmc['emu_file']
        elif self.get_workspace():
            self.__emu_file = os.path.join(self.get_workspace(),
                                           "data",
                                           "{}.emu".
                                           format(self.__vendor_type))
        else:
            self.__emu_file = "/usr/local/etc/infrasim/{0}/{0}.emu".\
                format(self.__vendor_type)

        if 'config_file' in self.__bmc:
            self.__config_file = self.__bmc['config_file']
        elif self.get_workspace():
            self.__config_file = os.path.join(self.get_workspace(),
                                              "data",
                                              "vbmc.conf")
        else:
            self.__config_file = "/etc/infrasim/vbmc.conf"

        if self.__sol_device:
            pass
        elif self.get_workspace():
            self.__sol_device = os.path.join(self.get_workspace(), ".pty0")
        else:
            self.__sol_device = "/etc/infrasim/pty0"

    def get_commandline(self):
        ipmi_cmd_str = "{0} -c {1} -f {2} -n -s /var/tmp".\
            format(self.__bin, self.__config_file, self.__emu_file)

        return ipmi_cmd_str


class CSocat(Task):
    def __init__(self):
        super(CSocat, self).__init__()

        self.__bin = None

        # Node wise attributes
        self.__port_serial = 9003
        self.__sol_device = ""

    def set_port_serial(self, port):
        self.__port_serial = port

    def set_sol_device(self, device):
        self.__sol_device = device

    def precheck(self):

        # check if socat exists
        try:
            code, socat_cmd = run_command("which /usr/bin/socat")
            self.__bin = socat_cmd.strip(os.linesep)
        except CommandRunFailed:
            raise CommandNotFound("/usr/bin/socat")

        # check ports are in use

        # check workspace
        if not self.__sol_device and not self.get_workspace():
            raise ArgsNotCorrect("No workspace and serial device are defined")

    def init(self):
        if self.__sol_device:
            pass
        elif self.get_workspace():
            self.__sol_device = os.path.join(self.get_workspace(), ".pty0")
        else:
            self.__sol_device = "/etc/infrasim/pty0"

    def get_commandline(self):
        socat_str = "{0} pty,link={1},waitslave " \
                    "udp-listen:{2},reuseaddr".\
            format(self.__bin, self.__sol_device, self.__port_serial)

        return socat_str


class CNode(object):
    def __init__(self, node_info):
        self.__tasks_list = []
        self.__node = node_info
        self.__node_name = "node-0"
        self.__numactl_obj = None
        self.workspace = ""

    def set_numactl(self, numactl_obj):
        self.__numactl_obj = numactl_obj

    def get_node_name(self):
        return self.__node_name

    def set_node_name(self, name):
        self.__node_name = name

    def precheck(self):
        for task in self.__tasks_list:
            task.precheck()

    def init_workspace(self):
        """
        Create workspace: <HOME>/.infrasim/<node_name>
        .infrasim/<node_name>    # Root folder
            data                 # Data folder
                infrasim.yml     # Save runtime infrasim.yml
                vbmc.conf        # Render template with data from infrasim.yml
                vbmc.emu         # Emulation data
                bios.bin         # BIOS
            script               # Script folder
                chassiscontrol
                lancontrol
                startcmd
                stopcmd
                resetcmd
            .pty0                # Serial device, created by socat, not here
            .<node_name>-socat   # pid file of socat
            .<node_name>-ipmi    # pid file of ipmi
            .<node_name>-qemu    # pid file of qemu
        What's done here:
            I. Create workspace
            II. Create log folder
            III. Create sub folder
            IV. Save infrasim.yml
            V. Render vbmc.conf, render scripts
            VI. Move emulation data, update identifiers, e.g. S/N
            VII. Move bios.bin
        """
        # I. Create workspace
        # if workspace exists, just do nothing and return
        self.workspace = "{}/.infrasim/{}".\
            format(os.environ["HOME"], self.get_node_name())
        if os.path.exists(self.workspace):
            return
        os.mkdir(self.workspace)

        # II. Create log folder
        path_log = "/var/log/infrasim/{}".format(self.get_node_name())
        if not os.path.exists(path_log):
            os.mkdir(path_log)

        # III. Create sub folder
        os.mkdir(os.path.join(self.workspace, "data"))
        os.mkdir(os.path.join(self.workspace, "script"))

        # IV. Save infrasim.yml
        yml_file = os.path.join(self.workspace, "data", "infrasim.yml")
        with open(yml_file, 'w') as fp:
            yaml.dump(self.__node, fp, default_flow_style=False)

        # V. Render vbmc.conf
        # and prepare bmc scripts
        if has_option(self.__node, "bmc", "config_file"):
            shutil.copy(self.__node["bmc"]["config_file"],
                        os.path.join(self.workspace, "data", "vbmc.conf"))
        else:
            bmc_obj = CBMC(self.__node.get("bmc", {}))

            # Render sctipts: startcmd, stopcmd, resetcmd, chassiscontrol
            # Copy scripts: lancontrol

            for target in ["startcmd", "stopcmd", "resetcmd"]:
                if not has_option(self.__node, "bmc", target):
                    src = os.path.join(TEMPLATE_ROOT, "script", target)
                    dst = os.path.join(self.workspace, "script", target)
                    with open(src, "r")as f:
                        src_text = f.read()
                    template = jinja2.Template(src_text)
                    dst_text = template.render(yml_file=yml_file)
                    with open(dst, "w") as f:
                        f.write(dst_text)
                    os.chmod(dst, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

            if not has_option(self.__node, "bmc", "startcmd"):
                path_startcmd = os.path.join(self.workspace,
                                             "script",
                                             "startcmd")
                bmc_obj.set_startcmd_script(path_startcmd)

            if not has_option(self.__node, "bmc", "chassiscontrol"):
                path_startcmd = os.path.join(self.workspace,
                                             "script",
                                             "startcmd")
                path_stopcmd = os.path.join(self.workspace,
                                            "script",
                                            "stopcmd")
                path_resetcmd = os.path.join(self.workspace,
                                             "script",
                                             "resetcmd")
                path_qemu_pid = os.path.join(self.workspace,
                                             ".{}-node".
                                             format(self.get_node_name()))
                src = os.path.join(TEMPLATE_ROOT, "script", "chassiscontrol")
                dst = os.path.join(self.workspace, "script", "chassiscontrol")
                with open(src, "r") as f:
                    src_text = f.read()
                template = jinja2.Template(src_text)
                dst_text = template.render(startcmd=path_startcmd,
                                           stopcmd=path_stopcmd,
                                           resetcmd=path_resetcmd,
                                           qemu_pid_file=path_qemu_pid)
                with open(dst, "w") as f:
                    f.write(dst_text)
                os.chmod(dst, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

                path_chassiscontrol = dst
                bmc_obj.set_chassiscontrol_script(path_chassiscontrol)

            if not has_option(self.__node, "bmc", "lancontrol"):
                os.symlink(os.path.join(TEMPLATE_ROOT,
                                        "script",
                                        "lancontrol"),
                           os.path.join(self.workspace,
                                        "script",
                                        "lancontrol"))

                path_lancontrol = os.path.join(self.workspace,
                                               "script",
                                               "lancontrol")
                bmc_obj.set_lancontrol_script(path_lancontrol)

            # Render connection port/device
            if has_option(self.__node, "type"):
                bmc_obj.set_type(self.__node["type"])

            if has_option(self.__node, "sol_device"):
                bmc_obj.set_sol_device(self.__node["sol_device"])

            if has_option(self.__node, "ipmi_console_port"):
                bmc_obj.set_port_ipmi_console(self.__node["ipmi_console_port"])

            if has_option(self.__node, "bmc_connection_port"):
                bmc_obj.set_port_qemu_ipmi(self.__node["bmc_connection_port"])

            bmc_obj.set_workspace(self.workspace)
            bmc_obj.init()
            bmc_obj.write_bmc_config(os.path.join(self.workspace,
                                                  "data",
                                                  "vbmc.conf"))

        # VI. Move emulation data
        # Update identifier accordingly
        path_emu_dst = os.path.join(self.workspace, "data")
        if has_option(self.__node, "bmc", "emu_file"):
            shutil.copy(self.__node["bmc"]["emu_file"], path_emu_dst)
        else:
            node_type = self.__node["type"]
            path_emu_src = "/usr/local/etc/infrasim/{0}/{0}.emu".\
                format(node_type)
            shutil.copy(path_emu_src, os.path.join(path_emu_dst, "{}.emu".
                                                   format(node_type)))

        # VII. Move bios.bin
        path_bios_dst = os.path.join(self.workspace, "data")
        if has_option(self.__node, "compute", "smbios"):
            shutil.copy(self.__node["compute"]["smbios"], path_bios_dst)
        else:
            node_type = self.__node["type"]
            path_bios_src = "/usr/local/etc/infrasim/{0}/{0}_smbios.bin".\
                format(node_type)
            shutil.copy(path_bios_src, os.path.join(path_emu_dst,
                                                    "{}_smbios.bin".
                                                    format(node_type)))
        # Place holder to sync serial number

    def terminate_workspace(self):
        os.system("rm -rf {}".format(self.workspace))

    def init(self):
        if self.__node['compute'] is None:
            raise Exception("No compute information")

        if 'name' in self.__node:
            self.set_node_name(self.__node['name'])

        self.init_workspace()

        socat_obj = CSocat()
        socat_obj.set_priority(0)
        socat_obj.set_task_name("{}-socat".format(self.__node_name))
        self.__tasks_list.append(socat_obj)

        bmc_obj = CBMC(self.__node.get('bmc', {}))
        bmc_obj.set_priority(1)
        bmc_obj.set_task_name("{}-bmc".format(self.__node_name))
        bmc_obj.set_log_path("/var/log/infrasim/{}/openipmi.log".
                             format(self.__node_name))
        self.__tasks_list.append(bmc_obj)

        compute_obj = CCompute(self.__node['compute'])
        compute_obj.set_run_mask(True)
        compute_obj.set_priority(2)
        compute_obj.set_task_name("{}-node".format(self.__node_name))
        compute_obj.set_log_path("/var/log/infrasim/{}/qemu.log".
                                 format(self.__node_name))
        self.__tasks_list.append(compute_obj)

        # Set interface
        if "type" not in self.__node:
            raise ArgsNotCorrect("Can't get infrasim type")
        else:
            bmc_obj.set_type(self.__node['type'])
            compute_obj.set_type(self.__node['type'])

        if "sol_device" in self.__node:
            socat_obj.set_sol_device(self.__node["sol_device"])
            bmc_obj.set_sol_device(self.__node["sol_device"])

        if "serial_port" in self.__node:
            socat_obj.set_port_serial(self.__node["serial_port"])
            compute_obj.set_port_serial(self.__node["serial_port"])

        if "ipmi_console_port" in self.__node:
            bmc_obj.set_port_ipmi_console(self.__node["ipmi_console_port"])
            # ipmi-console shall connect to same port with the same conf file

        if "bmc_connection_port" in self.__node:
            bmc_obj.set_port_qemu_ipmi(self.__node["bmc_connection_port"])
            compute_obj.set_port_qemu_ipmi(self.__node["bmc_connection_port"])

        for task in self.__tasks_list:
            task.set_workspace(self.workspace)
            task.init()

    # Run tasks list as the priority
    def start(self):
        # sort the tasks as the priority
        self.__tasks_list.sort(key=lambda x: x.get_priority(), reverse=False)

        for task in self.__tasks_list:
            task.run()

    def stop(self):
        # sort the tasks as the priority in reversed sequence
        self.__tasks_list.sort(key=lambda x: x.get_priority(), reverse=True)

        for task in self.__tasks_list:
            task.terminate()

    def status(self):
        for task in self.__tasks_list:
            task.status()


"""
class CChassis(object):
    def __init__(self, chassis_info):
        self.__chassis = chassis_info
        self.__chassis_model = None
        self.__node_list = []
        self.__numactl_obj = NumaCtl()

    def precheck(self):
        # check total resources
        for node in self.__node_list:
            node.precheck()

    def init(self):
        for node in self.__chassis['nodes']:
            node_obj = CNode(node)
            node_obj.set_node_name(self.__chassis['name'])
            self.__node_list.append(node_obj)

        for node_obj in self.__node_list:
            node_obj.init()

    def start(self, node_id=None):
        for node_obj in self.__node_list:
            if node_id and node_obj.get_node_name() == node_id:
                node_obj.start()
                return

        for node_obj in self.__node_list:
            node_obj.start()

    def stop(self, node_id=None):
        for node_obj in self.__node_list:
            if node_id and node_obj.get_node_name() == node_id:
                node_obj.stop()
                return

        for node_obj in self.__node_list:
            node_obj.stop()

    def status(self):
        for node_obj in self.__node_list:
            node_obj.status()
"""

class NumaCtl(object):
    def __init__(self):
        self.__cpu_list = []
        self.__node_list = []
        self.__numactl_table = {}
        numactl_show_output = Utility.run_command("numactl --show")
        for line in numactl_show_output.split(os.linesep):
            if line.startswith("physcpubind:"):
                self.__cpu_list = [int(x) for x in line.split(':')[1].strip().split()]

            if line.startswith("nodebind:"):
                self.__node_list = [int(x) for x in line.split(':')[1].strip().split()]

        numactl_hardware_output = Utility.run_command("numactl --hardware")
        for node_index in self.__node_list:
            self.__numactl_table[node_index] = []
            for line in numactl_hardware_output.split(os.linesep):
                if line.startswith("node {} cpus:".format(node_index)):
                    self.__numactl_table[node_index] = [int(x) for x in line.split(':')[1].strip().split()]

    def get_cpu_list(self, num):
        for i in self.__node_list:
            if len(self.__numactl_table[i]) >= num:
                return [self.__numactl_table[i].pop() for _ in range(0, num)]

        returned_cpu_list = []
        for i in self.__node_list:
            while (len(self.__numactl_table[i])) > 0:
                returned_cpu_list.append(self.__numactl_table[i].pop())
                if len(returned_cpu_list) == num:
                    return returned_cpu_list

        return returned_cpu_list
