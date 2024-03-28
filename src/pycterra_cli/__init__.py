import argparse
import inspect
import logging
import os
import re
import sys
import typing
from datetime import date
from pprint import pprint
from uuid import UUID

from picterra import (  # https://github.com/Picterra/picterra-python/tree/master
    APIClient,
    client,
)
from pkg_resources import get_distribution

__version__ = get_distribution("pycterra_cli").version

picterra_version = get_distribution("picterra").version

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.CRITICAL)


def _cmd_arg_to_api_arg(cmd: str):
    return cmd.replace("-", "_")


def api_arg_to_cmd_arg(fun: str):
    return fun.replace("_", "-")


def is_optional(field):
    if (typing.get_origin(field) is typing.Union and type(None) in typing.get_args(
        field
    )) or (len(typing.get_args(field)) > 1 and type(None) in typing.get_args(field)):
        return next(a for a in typing.get_args(field) if a is not type(None))
    else:
        return False


def uuid_type(uuid_to_test: str, version: int = 4):
    """
    Check if uuid_to_test is a valid UUID and returns it as a string

    Note that we cannot just pass 'type=UUID' because in case of POSTing
    these type of variables argparse would pass the UUID object and then
    requests would complain that is not JSON-serializable
    """
    try:
        UUID(uuid_to_test, version=version)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid UUID value: '{uuid_to_test}'")
    return str(uuid_to_test)


commands_map: dict[str, dict] = {}


def _handle_command(options):
    if options.verbose:
        if options.verbose >= 3:
            logger.setLevel(logging.DEBUG)
        elif options.verbose == 2:
            logger.setLevel(logging.INFO)
        elif options.verbose == 1:
            logger.setLevel(logging.WARNING)
    logger.debug(f"Logging level: {logging.getLevelName(logger.level)}")
    logger.debug(f"Handling command: {options}")
    if "PICTERRA_API_KEY" not in os.environ:
        logger.error("Missing API key")
        err = "Missing 'PICTERRA_API_KEY' environment variable"
        sys.exit("\033[91m%s\033[00m" % err)
    command_name = options.command
    param_names = commands_map[command_name].keys()
    logger.debug(f"Parameters are: {commands_map[command_name]}")
    api_client = APIClient()
    logger.debug("Instanciated API client")
    method_name = _cmd_arg_to_api_arg(command_name)
    try:
        method = getattr(api_client, method_name)
        args = {param: getattr(options, param) for param in param_names}
        logger.info(f"Executing {command_name} with {args}")
        res = method(**args)
        if res is not None:
            logger.info("Method returned something")
            if isinstance(res, client.ResultsPage):
                res = list(res)
            pprint(res)
        else:
            logger.info("Method did not return anything")
    except (client.APIError, ValueError) as err:
        logger.error(f"Got error from API: {err}")
        sys.exit("\033[91m%s\033[00m" % err)
    except Exception as ex:
        logger.critical(ex)


def parse_args(args):
    # TODO
    description = f"Picterra Python API Client (v {picterra_version}) CLI tool"
    members = inspect.getmembers(APIClient, predicate=inspect.isfunction)
    # create the top-level parser
    parser = argparse.ArgumentParser(
        prog="pycterra",
        description=description,
        epilog="© Andrea Orlandi " + str(date.today().year),
    )
    # Parser for version and verbosity
    parser.add_argument("--version", action="version", version=__version__)
    # Default parser
    parser.set_defaults(func=lambda _: parser.print_help())
    # Create the parser for the subcommands
    subparsers = parser.add_subparsers(dest="command")
    # For each method, create an appropriate subcommand
    for m in members:
        logger.debug(f"Got method {m}")
        name, fun = m
        if name.startswith("_"):
            logger.debug(f"Skipping method {m}")
            continue
        parameters_names = [
            f for f in inspect.signature(fun).parameters.keys() if f != "self"
        ]
        param_initials = [p[0] for p in parameters_names]
        parameters_have_different_initials = len(set(param_initials)) == len(
            param_initials
        )
        logger.debug(f"Got {parameters_names=}")
        docstring_lines = [
            d.strip().replace("%", "%%")  # https://bugs.python.org/issue41289
            for d in fun.__doc__.split("\n")
            if len(d.strip()) != 0
        ] if fun.__doc__ else []
        subcommand_name = api_arg_to_cmd_arg(name)
        try:
            cmd_doc_line = next(
                d
                for d in docstring_lines
                if "beta" not in d and "experimental" not in d
            )
            cmd_help = cmd_doc_line.strip()
        except StopIteration:
            cmd_help = None
            logger.warning(f"Method {m} has no help")
        subcommand_parser = subparsers.add_parser(
            subcommand_name, description=cmd_help, help=cmd_help
        )
        subcommand_parser.add_argument(
            "--verbose", "-v", action="count", default=0, help="verbosity level (1-3)"
        )
        required = subcommand_parser.add_argument_group("command required arguments")
        optional = subcommand_parser.add_argument_group("command optional arguments")
        commands_map[subcommand_name] = {}
        for param in parameters_names:
            logger.debug(f"Analyzing {param=}")
            param_type = inspect.signature(fun).parameters[param].annotation
            default = inspect.signature(fun).parameters[param].default
            subcommand_args = {}
            param_has_default = default != inspect.Parameter.empty
            param_is_required = not param_has_default
            subcommand_args["required"] = param_is_required
            choices = None
            if param_has_default:
                logger.debug(f"{param=} has default value {default}")
                subcommand_args["default"] = default
            else:
                logger.debug(f"{param=} has no default value")
            logger.debug(f"{param=} has {param_type=}")
            if param_type == inspect.Parameter.empty:
                logger.warning(f"Parameter {param} has no type")
            elif param_type == bool or param_type == typing.Optional[bool]:
                subcommand_args["action"] = argparse.BooleanOptionalAction
            elif param_type == str and param.endswith("_id"):
                subcommand_args["type"] = uuid_type
            elif param_type in (int, float, str):
                subcommand_args["type"] = param_type
            elif is_optional(param_type):
                subcommand_args["type"] = is_optional(param_type)
            elif typing.get_origin(param_type) is typing.Literal:
                choices = typing.get_args(param_type)
                for t in (int, float, str):
                    if all(isinstance(c, t) for c in choices):
                        subcommand_args["type"] = t
                        break
            try:
                param_doc_line = next(
                    line for line in docstring_lines if line.startswith(param)
                )
                split = param_doc_line.split(":")
                if len(split) >= 2 and not choices:
                    subcommand_args["help"] = split[1].strip() + (f' [{subcommand_args["type"].__name__}]' if "type" in subcommand_args else "")
                    match = re.match(
                        r".*one of \(?\s?((?:'?\w+'?,?\s?)+)",
                        subcommand_args["help"],
                        re.I,
                    )
                    if match:
                        choices = [
                            s.strip()
                            for s in match.group(1).replace("'", "").split(",")
                        ]
                else:
                    logger.warning(f"Parameter {param} has no help in {param_doc_line}")
            except StopIteration:
                logger.warning(f"Parameter {param} has no help")
            # TODO
            if choices:
                subcommand_args["choices"] = choices
                logger.debug(f"Parameter {param} possible values: {','.join(choices)}")
            name_or_flags = ["--" + api_arg_to_cmd_arg(param)]
            if (
                parameters_have_different_initials
                and param[0] != "v"
                and param[0] != "h"
            ):
                name_or_flags.append("-" + param[0])
            arg_text = f"argument {name_or_flags} with {subcommand_args}"
            if param_is_required:
                required.add_argument(
                    *name_or_flags,
                    **subcommand_args,
                )
                logger.debug(f"Adding required {arg_text}")
            else:
                optional.add_argument(
                    *name_or_flags,
                    **subcommand_args,
                )
                logger.debug(f"Adding optional {arg_text}")
            commands_map[subcommand_name][param] = subcommand_args.get(
                "type", subcommand_args.get("action", None)
            )
        logger.debug(f"Setting command for {subcommand_parser}")
        subcommand_parser.set_defaults(func=_handle_command)
    # Parse the command input
    args = parser.parse_args(args)
    # Branch depending on command
    args.func(args)
    return args


def main():
    parse_args(sys.argv[1:])
