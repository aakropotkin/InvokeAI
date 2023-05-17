# Copyright (c) 2023 Lincoln Stein (https://github.com/lstein)

'''Invokeai configuration system.

Arguments and fields are taken from the pydantic definition of the
model.  Defaults can be set by creating a yaml configuration file that
has a top-level key of "InvokeAI" and subheadings for each of the
categories returned by `invokeai --help`. The file looks like this:

[file: invokeai.yaml]

InvokeAI:
  Paths:
    root: /home/lstein/invokeai-main
    conf_path: configs/models.yaml
    legacy_conf_dir: configs/stable-diffusion
    outdir: outputs
    embedding_dir: embeddings
    lora_dir: loras
    autoconvert_dir: null
    gfpgan_model_dir: models/gfpgan/GFPGANv1.4.pth
  Models:
    model: stable-diffusion-1.5
    embeddings: true
  Memory/Performance:
    xformers_enabled: false
    sequential_guidance: false
    precision: float16
    max_loaded_models: 4
    always_use_cpu: false
    free_gpu_mem: false
  Features:
    nsfw_checker: true
    restore: true
    esrgan: true
    patchmatch: true
    internet_available: true
    log_tokenization: false
  Cross-Origin Resource Sharing:
    allow_origins: []
    allow_credentials: true
    allow_methods:
    - '*'
    allow_headers:
    - '*'
  Web Server:
    host: 127.0.0.1
    port: 8081

The default name of the configuration file is `invokeai.yaml`, located
in INVOKEAI_ROOT. You can replace supersede this by providing any
OmegaConf dictionary object initialization time:

 omegaconf = OmegaConf.load('/tmp/init.yaml')
 conf = InvokeAIAppConfig(conf=omegaconf)

By default, InvokeAIAppConfig will parse the contents of `sys.argv` at
initialization time. You may pass a list of strings in the optional
`argv` argument to use instead of the system argv:

 conf = InvokeAIAppConfig(arg=['--xformers_enabled'])

It is also possible to set a value at initialization time. This value
has highest priority.

 conf = InvokeAIAppConfig(xformers_enabled=True)

Any setting can be overwritten by setting an environment variable of
form: "INVOKEAI_<setting>", as in:

  export INVOKEAI_port=8080

Order of precedence (from highest):
   1) initialization options
   2) command line options
   3) environment variable options
   4) config file options
   5) pydantic defaults

Typical usage:

 from invokeai.app.services.config import InvokeAIAppConfig
 from invokeai.invocations.generate import TextToImageInvocation

 # get global configuration and print its nsfw_checker value
 conf = InvokeAIAppConfig()
 print(conf.nsfw_checker)

 # get the text2image invocation and print its step value
 text2image = TextToImageInvocation()
 print(text2image.steps)

Computed properties:

The InvokeAIAppConfig object has a series of properties that
resolve paths relative to the runtime root directory. They each return
a Path object:

 root_path          - path to InvokeAI root
 output_path        - path to default outputs directory
 model_conf_path    - path to models.yaml
 conf               - alias for the above
 embedding_path     - path to the embeddings directory
 lora_path          - path to the LoRA directory
 
In most cases, you will want to create a single InvokeAIAppConfig
object for the entire application. The get_invokeai_config() function
does this:

  config = get_invokeai_config()
  print(config.root)

# Subclassing

If you wish to create a similar class, please subclass the
`InvokeAISettings` class and define a Literal field named "type",
which is set to the desired top-level name.  For example, to create a
"InvokeBatch" configuration, define like this:

  class InvokeBatch(InvokeAISettings):
     type: Literal["InvokeBatch"] = "InvokeBatch"
     node_count : int = Field(default=1, description="Number of nodes to run on", category='Resources')
     cpu_count  : int = Field(default=8, description="Number of GPUs to run on per node", category='Resources')

This will now read and write from the "InvokeBatch" section of the
config file, look for environment variables named INVOKEBATCH_*, and
accept the command-line arguments `--node_count` and `--cpu_count`. The
two configs are kept in separate sections of the config file:

  # invokeai.yaml

  InvokeBatch:
     Resources:
        node_count: 1
        cpu_count: 8

  InvokeAI:
     Paths:
        root: /home/lstein/invokeai-main
        conf_path: configs/models.yaml
        legacy_conf_dir: configs/stable-diffusion
        outdir: outputs
     ...
'''
import argparse
import typing
import os
import sys
from argparse import ArgumentParser
from omegaconf import OmegaConf, DictConfig
from pathlib import Path
from pydantic import BaseSettings, Field, parse_obj_as
from typing import Any, ClassVar, Dict, List, Literal, Type, Union, get_origin, get_type_hints, get_args

INIT_FILE = Path('invokeai.yaml')
LEGACY_INIT_FILE = Path('invokeai.init')

# This global stores a singleton InvokeAIAppConfig configuration object
global_config = None

class InvokeAISettings(BaseSettings):
    '''
    Runtime configuration settings in which default values are
    read from an omegaconf .yaml file.
    '''
    initconf             : ClassVar[DictConfig] = None
    argparse_groups      : ClassVar[Dict] = {}

    def parse_args(self, argv: list=sys.argv[1:]):
        parser = self.get_parser()
        opt, _ = parser.parse_known_args(argv)
        for name in self.__fields__:
            if name not in self._excluded():
                setattr(self, name, getattr(opt,name))

    def to_yaml(self)->str:
        """
        Return a YAML string representing our settings. This can be used
        as the contents of `invokeai.yaml` to restore settings later.
        """
        cls = self.__class__
        type = get_args(get_type_hints(cls)['type'])[0]
        field_dict = dict({type:dict()})
        for name,field in self.__fields__.items():
            if name in cls._excluded():
                continue
            category = field.field_info.extra.get("category") or "Uncategorized"
            value = getattr(self,name)
            if category not in field_dict[type]:
                field_dict[type][category] = dict()
            # keep paths as strings to make it easier to read
            field_dict[type][category][name] = str(value) if isinstance(value,Path) else value
        conf = OmegaConf.create(field_dict)
        return OmegaConf.to_yaml(conf)

    @classmethod
    def add_parser_arguments(cls, parser):
        if 'type' in get_type_hints(cls):
            settings_stanza = get_args(get_type_hints(cls)['type'])[0]
        else:
            settings_stanza = "Uncategorized"
            
        env_prefix = cls.Config.env_prefix if hasattr(cls.Config,'env_prefix') else settings_stanza.upper()

        initconf = cls.initconf.get(settings_stanza) \
            if cls.initconf and settings_stanza in cls.initconf \
               else OmegaConf.create()

        fields = cls.__fields__
        cls.argparse_groups = {}
        for name, field in fields.items():
            if name not in cls._excluded():
                current_default = field.default
                
                category = field.field_info.extra.get("category","Uncategorized")
                env_name = env_prefix + '_' + name
                if category in initconf and name in initconf.get(category):
                    field.default = initconf.get(category).get(name)
                if env_name in os.environ:
                    field.default = os.environ[env_name]
                cls.add_field_argument(parser, name, field)

                field.default = current_default

    @classmethod
    def cmd_name(self, command_field: str='type')->str:
        hints = get_type_hints(self)
        if command_field in hints:
            return get_args(hints[command_field])[0]
        else:
            return 'Uncategorized'

    @classmethod
    def get_parser(cls)->ArgumentParser:
        parser = ArgumentParser(
            prog=cls.cmd_name(),
            description=cls.__doc__,
        )
        cls.add_parser_arguments(parser)
        return parser

    @classmethod
    def add_subparser(cls, parser: argparse.ArgumentParser):
        parser.add_parser(cls.cmd_name(), help=cls.__doc__)

    @classmethod
    def _excluded(self)->List[str]:
        return ['type','initconf']
    
    class Config:
        env_file_encoding = 'utf-8'
        arbitrary_types_allowed = True
        case_sensitive = True

    @classmethod
    def add_field_argument(cls, command_parser, name: str, field, default_override = None):
        field_type = get_type_hints(cls).get(name)
        default = default_override if default_override is not None else field.default if field.default_factory is None else field.default_factory()
        if category := field.field_info.extra.get("category"):
            if category not in cls.argparse_groups:
                cls.argparse_groups[category] = command_parser.add_argument_group(category)
            argparse_group = cls.argparse_groups[category]
        else:
            argparse_group = command_parser
        
        if get_origin(field_type) == Literal:
            allowed_values = get_args(field.type_)
            allowed_types = set()
            for val in allowed_values:
                allowed_types.add(type(val))
            allowed_types_list = list(allowed_types)
            field_type = allowed_types_list[0] if len(allowed_types) == 1 else Union[allowed_types_list]  # type: ignore

            argparse_group.add_argument(
                f"--{name}",
                dest=name,
                type=field_type,
                default=default,
                choices=allowed_values,
                help=field.field_info.description,
            )

        elif get_origin(field_type) == list:
            argparse_group.add_argument(
                f"--{name}",
                dest=name,
                nargs='*',
                type=field.type_,
                default=default,
                action=argparse.BooleanOptionalAction if field.type_==bool else 'store',
                help=field.field_info.description,
            )
        else:
            argparse_group.add_argument(
                f"--{name}",
                dest=name,
                type=field.type_,
                default=default,
                action=argparse.BooleanOptionalAction if field.type_==bool else 'store',
                help=field.field_info.description,
            )
def _find_root()->Path:
    if os.environ.get("INVOKEAI_ROOT"):
        root = Path(os.environ.get("INVOKEAI_ROOT")).resolve()
    elif (
            os.environ.get("VIRTUAL_ENV")
            and (Path(os.environ.get("VIRTUAL_ENV"), "..", INIT_FILE).exists()
                 or
                 Path(os.environ.get("VIRTUAL_ENV"), "..", LEGACY_INIT_FILE).exists()
                 )
    ):
        root = Path(os.environ.get("VIRTUAL_ENV"), "..").resolve()
    else:
        root = Path("~/invokeai").expanduser().resolve()
    return root

class InvokeAIAppConfig(InvokeAISettings):
    '''
    Application-wide settings.
    '''
    #fmt: off
    type: Literal["InvokeAI"] = "InvokeAI"
    root                : Path = Field(default=_find_root(), description='InvokeAI runtime root directory', category='Paths')
    conf_path           : Path = Field(default='configs/models.yaml', description='Path to models definition file', category='Paths')
    legacy_conf_dir     : Path = Field(default='configs/stable-diffusion', description='Path to directory of legacy checkpoint config files', category='Paths')
    model               : str = Field(default='stable-diffusion-1.5', description='Initial model name', category='Models')
    outdir              : Path = Field(default='outputs', description='Default folder for output images', category='Paths')
    embedding_dir       : Path = Field(default='embeddings', description='Path to InvokeAI textual inversion aembeddings directory', category='Paths')
    lora_dir            : Path = Field(default='loras', description='Path to InvokeAI LoRA model directory', category='Paths')
    autoconvert_dir     : Path = Field(default=None, description='Path to a directory of ckpt files to be converted into diffusers and imported on startup.', category='Paths')
    gfpgan_model_dir    : Path = Field(default="./models/gfpgan/GFPGANv1.4.pth", description='Path to GFPGAN models directory.', category='Paths')
    embeddings          : bool = Field(default=True, description='Load contents of embeddings directory', category='Models')
    xformers_enabled    : bool = Field(default=True, description="Enable/disable memory-efficient attention", category='Memory/Performance')
    sequential_guidance : bool = Field(default=False, description="Whether to calculate guidance in serial instead of in parallel, lowering memory requirements", category='Memory/Performance')
    precision           : Literal[tuple(['auto','float16','float32','autocast'])] = Field(default='float16',description='Floating point precision', category='Memory/Performance')
    max_loaded_models   : int = Field(default=2, gt=0, description="Maximum number of models to keep in memory for rapid switching", category='Memory/Performance')
    always_use_cpu      : bool = Field(default=False, description="If true, use the CPU for rendering even if a GPU is available.", category='Memory/Performance')
    free_gpu_mem        : bool = Field(default=False, description="If true, purge model from GPU after each generation.", category='Memory/Performance')
    nsfw_checker        : bool = Field(default=True, description="Enable/disable the NSFW checker", category='Features')
    restore             : bool = Field(default=True, description="Enable/disable face restoration code", category='Features')
    esrgan              : bool = Field(default=True, description="Enable/disable upscaling code", category='Features')
    patchmatch          : bool = Field(default=True, description="Enable/disable patchmatch inpaint code", category='Features')
    internet_available  : bool = Field(default=True, description="If true, attempt to download models on the fly; otherwise only use local models", category='Features')
    log_tokenization    : bool = Field(default=False, description="Enable logging of parsed prompt tokens.", category='Features')
    allow_origins       : List[str] = Field(default=[], description="Allowed CORS origins", category='Cross-Origin Resource Sharing')
    allow_credentials   : bool = Field(default=True, description="Allow CORS credentials", category='Cross-Origin Resource Sharing')
    allow_methods       : List[str] = Field(default=["*"], description="Methods allowed for CORS", category='Cross-Origin Resource Sharing')
    allow_headers       : List[str] = Field(default=["*"], description="Headers allowed for CORS", category='Cross-Origin Resource Sharing')
    host                : str = Field(default="127.0.0.1", description="IP address to bind to", category='Web Server')
    port                : int = Field(default=9090, description="Port to bind to", category='Web Server')
    #fmt: on

    def __init__(self, conf: DictConfig = None, argv: List[str]=None, **kwargs):
        '''
        Initialize InvokeAIAppconfig.
        :param conf: alternate Omegaconf dictionary object
        :param argv: aternate sys.argv list
        :param **kwargs: attributes to initialize with
        '''
        super().__init__(**kwargs)
        
        # Set the runtime root directory. We parse command-line switches here
        # in order to pick up the --root_dir option.
        self.parse_args(argv)
        if conf is None:
            try:
                conf = OmegaConf.load(self.root_dir / INIT_FILE)
            except:
                pass
        InvokeAISettings.initconf = conf

        # parse args again in order to pick up settings in configuration file
        self.parse_args(argv)

        # restore initialization values
        hints = get_type_hints(self)
        for k in kwargs:
            setattr(self,k,parse_obj_as(hints[k],kwargs[k]))

    @property
    def root_path(self)->Path:
        '''
        Path to the runtime root directory
        '''
        if self.root:
            return Path(self.root).expanduser()
        else:
            return self.find_root()

    @property
    def root_dir(self)->Path:
        '''
        Alias for above.
        '''
        return self.root_path

    def _resolve(self,partial_path:Path)->Path:
        return (self.root_path / partial_path).resolve()

    @property
    def output_path(self)->Path:
        '''
        Path to defaults outputs directory.
        '''
        return self._resolve(self.outdir)

    @property
    def model_conf_path(self)->Path:
        '''
        Path to models configuration file.
        '''
        return self._resolve(self.conf_path)

    @property
    def legacy_conf_path(self)->Path:
        '''
        Path to directory of legacy configuration files (e.g. v1-inference.yaml)
        '''
        return self._resolve(self.legacy_conf_dir)

    @property
    def cache_dir(self)->Path:
        '''
        Path to the global cache directory for HuggingFace hub-managed models
        '''
        return self.models_dir / "hub"

    @property
    def models_dir(self)->Path:
        '''
        Path to the models directory
        '''
        return self._resolve("models")

    @property
    def embedding_path(self)->Path:
        '''
        Path to the textual inversion embeddings directory.
        '''
        return self._resolve(self.embedding_dir) if self.embedding_dir else None
    
    @property
    def lora_path(self)->Path:
        '''
        Path to the LoRA models directory.
        '''
        return self._resolve(self.lora_dir) if self.lora_dir else None

    @property
    def autoconvert_path(self)->Path:
        '''
        Path to the directory containing models to be imported automatically at startup.
        '''
        return self._resolve(self.autoconvert_dir) if self.autoconvert_dir else None

    @property
    def gfpgan_model_path(self)->Path:
        '''
        Path to the GFPGAN model.
        '''
        return self._resolve(self.gfpgan_model_dir) if self.gfpgan_model_dir else None

    # the following methods support legacy calls leftover from the Globals era
    @property
    def full_precision(self)->bool:
        """Return true if precision set to float32"""
        return self.precision=='float32'

    @property
    def disable_xformers(self)->bool:
        """Return true if xformers_enabled is false"""
        return not self.xformers_enabled

    @property
    def try_patchmatch(self)->bool:
        """Return true if patchmatch true"""
        return self.patchmatch

    @staticmethod
    def find_root()->Path:
        '''
        Choose the runtime root directory when not specified on command line or
        init file.
        '''
        return _find_root()

def get_invokeai_config(cls:Type[InvokeAISettings]=InvokeAIAppConfig)->InvokeAISettings:
    '''
    This returns a singleton InvokeAIAppConfig configuration object.
    '''
    global global_config
    if global_config is None or type(global_config)!=cls:
        global_config = cls()
    return global_config
