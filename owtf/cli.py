"""
owtf.cli

This is the command-line front-end in charge of processing arguments and call the framework.
"""

from __future__ import print_function

import os
import sys
import logging

from owtf.core import Core
from owtf.dependency_management.component_initialiser import ComponentInitialiser, DatabaseNotRunningException
from owtf.dependency_management.dependency_resolver import ServiceLocator
from owtf.lib.cli_options import usage, parse_options


def banner():
    """Prints a figlet type banner"""

    print("""\033[92m
 _____ _ _ _ _____ _____
|     | | | |_   _|   __|
|  |  | | | | | | |   __|
|_____|_____| |_| |__|

        @owtfp
    http://owtf.org
    \033[0m""")


def get_plugins_from_arg(arg):
    """ Returns a list of requested plugins and plugin groups

    :param arg: Comma separated list of plugins
    :type arg: `str`
    :return: List of plugins and plugin groups
    :rtype: `list`
    """
    plugins = arg.split(',')
    plugin_groups = ServiceLocator.get_component("db_plugin").get_groups_for_plugins(plugins)
    if len(plugin_groups) > 1:
        usage("The plugins specified belong to several plugin groups: '%s'" % str(plugin_groups))
    return [plugins, plugin_groups]


def process_options(user_args):
    """ The main argument processing function

    :param user_args: User supplied arguments
    :type user_args: `str`
    :return: A dictionary of arguments
    :rtype: `dict`
    """
    try:
        db_plugin = ServiceLocator.get_component("db_plugin")
        valid_groups = db_plugin.get_all_plugin_groups()
        valid_types = db_plugin.get_all_plugin_types() + ['all', 'quiet']
        arg = parse_options(user_args, valid_groups, valid_types)
    except KeyboardInterrupt as e:
        usage("Invalid OWTF option(s) %s" % e)
        sys.exit(0)

    # Default settings:
    profiles = {}
    plugin_group = arg.PluginGroup

    if arg.CustomProfile:  # Custom profiles specified
        # Quick pseudo-validation check
        for profile in arg.CustomProfile.split(','):
            chunks = profile.split(':')
            if len(chunks) != 2 or not os.path.exists(chunks[1]):
                usage("Invalid Profile")
            else:  # profile "ok" :)
                profiles[chunks[0]] = chunks[1]

    if arg.OnlyPlugins:
        arg.OnlyPlugins, plugin_groups = get_plugins_from_arg(arg.OnlyPlugins)
        try:
            # Set Plugin Group according to plugin list specified
            plugin_group = plugin_groups[0]
        except IndexError:
            usage("Please use either OWASP/OWTF codes or Plugin names")
        logging.info("Defaulting Plugin Group to '%s' based on list of plugins supplied" % plugin_group)

    if arg.ExceptPlugins:
        arg.ExceptPlugins, plugin_groups = get_plugins_from_arg(arg.ExceptPlugins)

    if arg.TOR_mode:
        arg.TOR_mode = arg.TOR_mode.split(":")
        if(arg.TOR_mode[0] == "help"):
            from owtf.http.proxy.tor_manager import TOR_manager
            TOR_manager.msg_configure_tor()
            exit(0)
        if len(arg.TOR_mode) == 1:
            if arg.TOR_mode[0] != "help":
                usage("Invalid argument for TOR-mode")
        elif len(arg.TOR_mode) != 5:
            usage("Invalid argument for TOR-mode")
        else:
            # Enables OutboundProxy.
            if arg.TOR_mode[0] == '':
                outbound_proxy_ip = "127.0.0.1"
            else:
                outbound_proxy_ip = arg.TOR_mode[0]
            if arg.TOR_mode[1] == '':
                outbound_proxy_port = "9050"  # default TOR port
            else:
                outbound_proxy_port = arg.TOR_mode[1]
            arg.OutboundProxy = "socks://%s:%s" % (outbound_proxy_ip, outbound_proxy_port)

    if arg.Botnet_mode:  # Checking arguments
        arg.Botnet_mode = arg.Botnet_mode.split(":")
        if arg.Botnet_mode[0] == "miner" and len(arg.Botnet_mode) != 1:
            usage("Invalid argument for Botnet mode\n Mode must be miner or list")
        if arg.Botnet_mode[0] == "list":
            if len(arg.Botnet_mode) != 2:
                usage("Invalid argument for Botnet mode\n Mode must be miner or list")
            if not os.path.isfile(os.path.expanduser(arg.Botnet_mode[1])):
                usage("Error Proxy List not found! Please check the path.")

    if arg.OutboundProxy:
        arg.OutboundProxy = arg.OutboundProxy.split('://')
        if len(arg.OutboundProxy) == 2:
            arg.OutboundProxy = arg.OutboundProxy + arg.OutboundProxy.pop().split(':')
            if arg.OutboundProxy[0] not in ["socks", "http"]:
                usage("Invalid argument for Outbound Proxy")
        else:
            arg.OutboundProxy = arg.OutboundProxy.pop().split(':')
        # OutboundProxy should be type://ip:port
        if (len(arg.OutboundProxy) not in [2, 3]):
            usage("Invalid argument for Outbound Proxy")
        else:  # Check if the port is an int.
            try:
                int(arg.OutboundProxy[-1])
            except ValueError:
                usage("Invalid port provided for Outbound Proxy")

    if arg.InboundProxy:
        arg.InboundProxy = arg.InboundProxy.split(':')
        # InboundProxy should be (ip:)port:
        if len(arg.InboundProxy) not in [1, 2]:
            usage("Invalid argument for Inbound Proxy")
        else:
            try:
                int(arg.InboundProxy[-1])
            except ValueError:
                usage("Invalid port for Inbound Proxy")

    plugin_types_for_group = db_plugin.get_types_for_plugin_group(plugin_group)
    if arg.PluginType == 'all':
        arg.PluginType = plugin_types_for_group
    elif arg.PluginType == 'quiet':
        arg.PluginType = ['passive', 'semi_passive']

    scope = arg.Targets or []  # Arguments at the end are the URL target(s)
    num_targets = len(scope)
    if plugin_group != 'auxiliary' and num_targets == 0 and not arg.list_plugins:
        # TODO: Fix this
        pass
    elif num_targets == 1:  # Check if this is a file
        if os.path.isfile(scope[0]):
            logging.info("Scope file: trying to load targets from it ..")
            new_scope = []
            for target in open(scope[0]).read().split("\n"):
                CleanTarget = target.strip()
                if not CleanTarget:
                    continue  # Skip blank lines
                new_scope.append(CleanTarget)
            if len(new_scope) == 0:  # Bad file
                usage("Please provide a scope file (1 target x line)")
            scope = new_scope

    for target in scope:
        if target[0] == "-":
            usage("Invalid Target: " + target)

    args = ''
    if plugin_group == 'auxiliary':
        # For auxiliary plugins, the scope are the parameters.
        args = scope
        # auxiliary plugins do not have targets, they have metasploit-like parameters.
        scope = ['auxiliary']

    return {
        'list_plugins': arg.list_plugins,
        'Force_Overwrite': arg.ForceOverwrite,
        'Interactive': arg.Interactive == 'yes',
        'Simulation': arg.Simulation,
        'Scope': scope,
        'argv': sys.argv,
        'PluginType': arg.PluginType,
        'OnlyPlugins': arg.OnlyPlugins,
        'ExceptPlugins': arg.ExceptPlugins,
        'InboundProxy': arg.InboundProxy,
        'OutboundProxy': arg.OutboundProxy,
        'OutboundProxyAuth': arg.OutboundProxyAuth,
        'Profiles': profiles,
        'PluginGroup': plugin_group,
        'RPort': arg.RPort,
        'PortWaves': arg.PortWaves,
        'ProxyMode': arg.ProxyMode,
        'TOR_mode': arg.TOR_mode,
        'Botnet_mode': arg.Botnet_mode,
        'nowebui': arg.nowebui,
        'Args': args
    }


def run_owtf(core, args):
    """This function calls core and loads the appropriate phases of component initialization

    :param core: core object
    :type core::Class:`owtf.core.Core`
    :param args: Arguments dictionary
    :type args: `dict`
    :return:
    :rtype: None
    """
    try:
        if core.start(args):
            # Only if Start is for real (i.e. not just listing plugins, etc)
            core.finish()  # Not Interrupted or Crashed.
    except KeyboardInterrupt:
        # NOTE: The user chose to interact: interactivity check redundant here:
        logging.warning("OWTF was aborted by the user:")
        logging.info("Please check report/plugin output files for partial results")
        # Interrupted. Must save the DB to disk, finish report, etc.
        core.finish()
    except SystemExit:
        pass  # Report already saved, framework tries to exit.
    finally:  # Needed to rename the temp storage dirs to avoid confusion.
        core.clean_temp_storage_dirs()


def main(args):
    """ The main wrapper which loads everything

    :param args: User supplied arguments dictionary
    :type args: `dict`
    :return:
    :rtype: None
    """
    banner()
    # Get tool path from script path:
    root_dir = os.path.dirname(os.path.abspath(args[0])) or '.'
    owtf_pid = os.getpid()

    try:
        ComponentInitialiser.initialisation_phase_1(root_dir, owtf_pid)
    except DatabaseNotRunningException:
        exit(-1)

    args = process_options(args[1:])
    ServiceLocator.get_component("config").process_phase1(args)
    ComponentInitialiser.initialisation_phase_2(args)

    # Initialise Framework.
    core = Core()
    logging.warn(
        "OWTF Version: %s, Release: %s " % (
            ServiceLocator.get_component("config").get_val('VERSION'),
            ServiceLocator.get_component("config").get_val('RELEASE'))
    )
    run_owtf(core, args)
