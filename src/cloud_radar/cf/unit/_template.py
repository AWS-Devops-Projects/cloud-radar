from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from cfn_tools import dump_yaml, load_yaml  # type: ignore

import yaml

from . import functions

IntrinsicFunc = Callable[["Template", Any], Any]


class Template:
    """Loads a Cloudformation template file so that it's parameters
    and conditions can be rendered into their final form for testing.
    """

    AccountId: str = "5" * 12
    NotificationARNs: list = []
    NoValue: str = ""  # Not yet implemented
    Partition: str = "aws"  # Other regions not implemented
    Region: str = "us-east-1"
    StackId: str = ""  # Not yet implemented
    StackName: str = ""  # Not yet implemented
    URLSuffix: str = "amazonaws.com"  # Other regions not implemented

    def __init__(
        self, template: Dict[str, Any], imports: Optional[Dict[str, str]] = None
    ) -> None:
        """Loads a Cloudformation template from a file and saves
        it as a dictionary.

        Args:
            template (Dict): The Cloudformation template as a dictionary.

        Raises:
            TypeError: If template is not a dictionary.
            TypeError: If imports is not a dictionary.
        """

        if imports is None:
            imports = {}

        if not isinstance(template, dict):
            raise TypeError(f"Template should be dict not {type(template).__name__}.")

        if not isinstance(imports, dict):
            raise TypeError(f"Imports should be dict not {type(imports).__name__}.")

        self.raw: str = yaml.dump(template)
        self.template = template
        self.Region = Template.Region
        self.imports = imports

    @classmethod
    def from_yaml(cls, template_path: Union[str, Path]) -> Template:

        with open(template_path) as f:
            raw = f.read()

        tmp_yaml = load_yaml(raw)

        tmp_str = dump_yaml(tmp_yaml)

        template = yaml.load(tmp_str, Loader=yaml.FullLoader)

        return cls(template)

    def render(
        self, params: Dict[str, str] = None, region: Union[str, None] = None
    ) -> dict:
        """Solves all conditionals, references and pseudo variables using
        the passed in parameters. After rendering the template all resources
        that wouldn't get deployed because of a condtion statement are removed.

        Args:
            params (dict, optional): Parameter names and values to be used when rendering.
            region (str, optional): The region is used for the AWS::Region pseudo variable. Defaults to "us-east-1".

        Returns:
            dict: The rendered template.
        """  # noqa: B950

        if region:
            self.Region = region

        self.template = yaml.load(self.raw, Loader=yaml.FullLoader)
        self.set_parameters(params)

        add_metadata(self.template, self.Region)

        self.resolve_values(self.template)

        resources = self.template["Resources"]
        for r_name, r_value in list(resources.items()):
            if "Condition" in r_value:
                condition = self.template["Conditions"][r_value["Condition"]]

                if not condition:
                    del self.template["Resources"][r_name]
                    continue

        return self.template

    def resolve_values(self, data: Any) -> Any:
        """Recurses through a Cloudformation template. Solving all
        references and variables along the way.

        Args:
            data (Any): Could be a dict, list, str or int.

        Returns:
            Any: Return the rendered data structure.
        """

        aws_functions: Dict[str, IntrinsicFunc] = {
            "Ref": functions.ref,
            "Fn::Equals": functions.equals,
            "Fn::If": functions.if_,
            "Fn::Sub": functions.sub,
            "Fn::Join": functions.join,
            "Fn::Base64": functions.base64,
            "Fn::Cidr": functions.cidr,
        }

        if isinstance(data, dict):
            for key, value in data.items():

                if key == "Ref":
                    return functions.ref(self, value)

                value = self.resolve_values(value)

                if key in aws_functions:
                    return aws_functions[key](self, value)

                data[key] = self.resolve_values(value)
            return data
        elif isinstance(data, list):
            return [self.resolve_values(item) for item in data]
        else:
            return data

    def set_parameters(self, parameters: Union[Dict[str, str], None] = None) -> None:
        """Sets the parameters for a template using the provided parameters or
        by using the default value of that parameter.

        Args:
            parameters (Union[Dict[str, str], None], optional): The parameters names and values. Defaults to None.

        Raises:
            ValueError: If you supply parameters for a template that doesn't have any.
            ValueError: If you pass parameters that are not in this template.
            ValueError: If Template Parameter is missing a default and a value is not provided.
        """  # noqa: B950

        if parameters is None:
            parameters = {}

        if "Parameters" not in self.template:
            if parameters:
                raise ValueError(
                    "You supplied parameters for a template that doesn't have any."
                )
            return

        t_params: dict = self.template["Parameters"]

        if set(parameters) - set(t_params):
            raise ValueError("You passed a Parameter that was not in the Template.")

        for p_name, p_value in t_params.items():
            if p_name in parameters:
                t_params[p_name]["Value"] = parameters[p_name]
                continue

            if "Default" not in p_value:
                raise ValueError(
                    "Must provide values for parameters that don't have a default value."
                )

            t_params[p_name]["Value"] = p_value["Default"]


def add_metadata(template: Dict, region: str) -> None:
    """This functions adds the current region to the template
    as metadate because we can't treat Region like a normal pseduo
    variables because we don't want to update the class var for every run.

    Args:
        template (Dict): The template you want to update.
        region (str): The region that template will be tested with.
    """

    metadata = {"Cloud-Radar": {"Region": region}}

    if "Metadata" not in template:
        template["Metadata"] = {}

    template["Metadata"].update(metadata)
