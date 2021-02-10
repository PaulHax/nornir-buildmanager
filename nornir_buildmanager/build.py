'''
  
*Note*: Certain arguments support regular expressions.  See the python :py:mod:`re` module for instructions on how to construct appropriate regular expressions.

.. argparse::
   :module: nornir_buildmanager.build
   :func: BuildParserRoot
   :prog: nornir_build volumepath

'''

import argparse
import logging
import os
import sys
import time

import matplotlib 
#Nornir build must use a backend that does not allocate windows in the GUI should be used. 
#Otherwise bugs will appear in multi-threaded environments
if not 'DEBUG' in os.environ: 
    matplotlib.use('Agg') 

import matplotlib.pyplot as plt
plt.ioff()

import nornir_buildmanager
from nornir_buildmanager import *
from nornir_imageregistration.files import *
from nornir_shared.misc import SetupLogging, lowpriority
from nornir_shared.tasktimer import TaskTimer
from pkg_resources import resource_filename

import nornir_shared.prettyoutput as prettyoutput

CommandParserDict = {}

 
def ConfigDataPath():
    return resource_filename(__name__, 'config')


def AddVolumeArgumentToParser(parser):
    parser.add_argument('volumepath',
                        action='store',
                        type=str,
                        help='The path to the volume',
                        )


def _AddParserRootArguments(parser):
    
    parser.add_argument('volumepath',
                        action='store',
                        type=str,
                        help='Directory containing volume to execute command on',
                        )
    
    parser.add_argument('-debug',
                        action='store_true',
                        required=False,
                        default=False,
                        help='If true any exceptions raised by pipelines are not handled.',
                        dest='debug')

    parser.add_argument('-lowpriority', '-lp',
                        action='store_true',
                        required=False,
                        default=False,
                        help='Run the build with lower priority.  The machine may be more responsive at the expense of much slower builds. 3x-5x slower in tests.',
                        dest='lowpriority')

    parser.add_argument('-verbose',
                        action='store_true',
                        required=False,
                        default=False,
                        help='Provide additional output',
                        dest='verbose')
    
#     parser.add_argument('-recover',
#                         action='store_true',
#                         required=False,
#                         default=False,
#                         help='Used to recover missing meta-data.  This searches child directories for VolumeData.xml files and re-links them to the parent element in volume path.  This command does not recurse and does not need to be run on the top-level volume directory.',
#                         dest='verbose')

def _AddRecoverNotesParser(root_parser, subparsers):
    recover_parser = subparsers.add_parser('RecoverNotes', help='Used to recover or update notes files in a folder.  This searches a path for *.txt files and creates/updates a notes element with the information in the file.',)
    recover_parser.set_defaults(func=call_recover_import_meta_data, parser=root_parser)
    
    recover_parser.add_argument('-save',
                         action='store_true',
                         required=False,
                         default=False,
                         help='Set this flag to save the VolumeData.xml files with the located linked elements included.',
                         dest='save_restoration')

def _AddRecoverParser(root_parser, subparsers):
    recover_parser = subparsers.add_parser('RecoverLinks', help='Used to recover missing meta-data.  This searches child directories for VolumeData.xml files and re-links them to the parent element in volume path.  This command does not recurse and does not need to be run on the top-level volume directory.',)
    recover_parser.set_defaults(func=call_recover_links, parser=root_parser)
    
    recover_parser.add_argument('-save',
                         action='store_true',
                         required=False,
                         default=False,
                         help='Set this flag to save the VolumeData.xml files with the located linked elements included.',
                         dest='save_restoration')
    

def _GetPipelineXMLPath():
    return os.path.join(ConfigDataPath(), 'Pipelines.xml')


def BuildParserRoot():

    # conflict_handler = 'resolve' replaces old arguments with new if both use the same option flag
    parser = argparse.ArgumentParser('Buildscript', conflict_handler='resolve', description='Options available to all build commands.  Specific pipelines may extend the argument list.')
    _AddParserRootArguments(parser)
    
    pipeline_subparsers = parser.add_subparsers(title='Commands')
    _AddRecoverParser(parser, pipeline_subparsers)
    _AddRecoverNotesParser(parser, pipeline_subparsers)
    #subparsers = parser.add_subparsers(title='Utilities')
    
    # subparsers = parser.add_subparsers(title='help')
    # help_parser = subparsers.add_parser('help', help='Print help information')
# 
    # help_parser.set_defaults(func=print_help, parser=parser)
    # help_parser.add_argument('pipelinename',
                        # default=None,
                        # nargs='?',
                        # type=str,
                        # help='Print help for a pipeline, or all pipelines if unspecified')

    # CommandParserDict['help'] = help_parser

    # update_parser = subparsers.add_parser('update', help='If directories have been copied directly into the volume this flag is required to detect them')
    
    _AddPipelineParsers(pipeline_subparsers)
    
    return parser


def _AddPipelineParsers(subparsers):

    PipelineXML = _GetPipelineXMLPath()
    # Load the element tree once and pass it to the later functions so we aren't parsing the XML text in the loop
    PipelineXML = pipelinemanager.PipelineManager.LoadPipelineXML(PipelineXML)

    for pipeline_name in pipelinemanager.PipelineManager.ListPipelines(PipelineXML):
        pipeline = pipelinemanager.PipelineManager.Load(PipelineXML, pipeline_name)

        pipeline_parser = subparsers.add_parser(pipeline_name, help=pipeline.Help, epilog=pipeline.Epilog)

        pipeline.GetArgParser(pipeline_parser, IncludeGlobals=True)

        pipeline_parser.set_defaults(func=call_pipeline, PipelineXmlFile=_GetPipelineXMLPath(), PipelineName=pipeline_name)

        CommandParserDict[pipeline_name] = pipeline_parser


def print_help(args):

    if args.pipelinename is None:
        args.parser.print_help() 
    elif args.pipelinename in CommandParserDict:
        parser = CommandParserDict[args.pipelinename]
        parser.print_help()
    else:
        args.parser.print_help()


def call_recover_links(args):
    '''This function checks for missing link elements in a volume and adds them back to the volume'''
    volumeObj = VolumeManagerETree.VolumeManager.Load(args.volumepath)
    volumeObj.RepairMissingLinkElements()
    
    if args.save_restoration:
        volumeObj.Save(recurse=False)
        prettyoutput.Log("Recovered links saved (if found).")
    else:
        prettyoutput.Log("Save flag not set, recovered links not saved.")
        
def call_recover_import_meta_data(args):
    '''This function checks for missing link elements in a volume and adds them back to the volume'''
    volumeObj = VolumeManagerETree.VolumeManager.Load(args.volumepath)
    notesAdded = nornir_buildmanager.importers.shared.TryAddNotes(volumeObj, volumeObj.FullPath, None)
    
    if not notesAdded:
        prettyoutput.Log(f"No notes recovered from {volumeObj.FullPath}.")
        return
    
    if notesAdded and args.save_restoration:
        volumeObj.Save(recurse=False)
        prettyoutput.Log("Recovered notes file saved.")
    else:
        prettyoutput.Log("Save flag not set, recovered notes, but not saved.")


def call_pipeline(args):
    pipelinemanager.PipelineManager.RunPipeline(PipelineXmlFile=args.PipelineXmlFile, PipelineName=args.PipelineName, args=args)

    
def _GetFromNamespace(ns, attribname, default=None):
    if attribname in ns:
        return getattr(ns, attribname)
    else:
        return default


def InitLogging(buildArgs):

#    nornir_shared.Misc.RunWithProfiler('Execute()', "C:/Temp/profile.pr")

    parser = BuildParserRoot()

    (args, extraargs) = parser.parse_known_args(buildArgs)

    if 'volumepath' in args:
        if _GetFromNamespace(args, 'debug', False):
            SetupLogging(OutputPath=args.volumepath, Level=logging.DEBUG)
        else:
            SetupLogging(Level=logging.WARN)
    else:
        SetupLogging(Level=logging.WARN)


def Execute(buildArgs=None):

    # Spend more time on each thread before switching
    #sys.setswitchinterval(500)

    if buildArgs is None:
        buildArgs = sys.argv[1:]

    InitLogging(buildArgs)

    Timer = TaskTimer()

    parser = BuildParserRoot()

    args = parser.parse_args(buildArgs)
   
    if args.lowpriority:
        
        lowpriority()
        print("Warning, using low priority flag.  This can make builds much slower")
        
    # SetupLogging(OutputPath=args.volumepath)
    cmdName = ''
    if hasattr(args, 'PipelineName'):
        cmdName = args.PipelineName
    elif len(buildArgs) >= 2:
        cmdName = buildArgs[1]
     
    try:   
        if cmdName is not None:
            Timer.Start(cmdName)

        args.func(args) 
        
    finally:
        if cmdName is not None: 
            Timer.End(cmdName)
            
        OutStr = str(Timer)
        prettyoutput.Log(OutStr)
        timeTextFullPath = os.path.join(args.volumepath, 'Timing.txt') 
        try:
            with open(timeTextFullPath, 'a') as OutputFile:
                OutputFile.writelines(OutStr)
                OutputFile.close()
        except:
            prettyoutput.Log('Could not write %s' % (timeTextFullPath))


if __name__ == '__main__':
    Execute()

