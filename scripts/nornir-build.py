#! /Library/Frameworks/Python.framework/Versions/Current/bin python

import sys
import os

import time
import argparse
import nornir_buildmanager.LowPriority as LowPriority
import nornir_shared.prettyoutput as prettyoutput
from nornir_shared.tasktimer import TaskTimer
import logging
from nornir_buildmanager import *
from nornir_imageregistration.io import *


def ConfigDataPath():

    try:
        path = os.path.dirname(__file__)
    except:
        path = os.getcwd()

    return os.path.join(path, 'config')


def ProcessArgs():

    # conflict_handler = 'resolve' replaces old arguments with new if both use the same option flag
    parser = argparse.ArgumentParser('Buildscript', conflict_handler='resolve')

    parser.add_argument('-input',
                        action='store',
                        required=False,
                        type=str,
                        default=None,
                        help='The path to the data to import',
                        dest='inputpath'
                        )

    parser.add_argument('-volume',
                        action='store',
                        required=True,
                        default=None,
                        type=str,
                        help='The path to the data to export',
                        dest='volumepath'
                        )

    parser.add_argument('-update',
                        action='store_true',
                        required=False,
                        default=False,
                        help='If directories have been copied directly into the volume this flag is required to detect them',
                        dest='update'
                        )

    parser.add_argument('-importmapxml',
                        action='store',
                        required=False,
                        type=str,
                        default='Importers.xml',
                        help='The importer XML file to use',
                        dest='importmapxmlpath'
                        )

    parser.add_argument('-pipelinexml',
                        action='store',
                        required=False,
                        default='Pipelines.xml',
                        type=str,
                        help='The path to the xml file containing the pipeline XML file',
                        dest='pipelinexmlpath'
                        )

    parser.add_argument('-pipeline',
                        action='store',
                        required=False,
                        default=None,
                        nargs='+',
                        type=str,
                        help='The names of the pipeline to use',
                        dest='pipelinenames'
                        )

    parser.add_argument('-debug',
                        action='store_true',
                        required=False,
                        default=False,
                        help='For debugging purposes exceptions are not handled',
                        dest='debug')

    parser.add_argument('-verbose',
                        action='store_true',
                        required=False,
                        default=False,
                        help='Provide additional output for debugging purposes.',
                        dest='verbose')

    # parser.add_argument('args', nargs=argparse.REMAINDER)
    return parser

def Execute(buildArgs=None):

    if buildArgs is None:
        buildArgs = sys.argv

    vikingURL = ""

    dargs = dict()
    # dargs.update(args.__dict__)

    TimingOutput = 'Timing.txt'

    LowPriority.lowpriority()

    Timer = TaskTimer()

    parser = ProcessArgs()

    (args, extraargs) = parser.parse_known_args(buildArgs)

    # SetupLogging(args.volumepath)

    try:
        Timer.Start('Total Runtime')

        Timer.Start('ADoc To Mosaic')

        Importer = None
        if not args.inputpath is None:
            ImporterXMLPath = os.path.join(ConfigDataPath(), args.importmapxmlpath)
            print "Loading import map: " + ImporterXMLPath
            Importer = ImportManager.ImportManager.Load(ImporterXMLPath)
            if(Importer is None):

                prettyoutput.LogErr("Specified Importer.xml not found: " + args.importmapxmlpath)
                sys.exit()

            Importer.ConvertAll(args.inputpath, args.volumepath)

        if args.update:
            volumeObj = VolumeManagerETree.load(args.volumepath)
            volumeObj.UpdateSubElements()

        if args.pipelinenames is None:
            return

        for pipelinename in args.pipelinenames:
            PipelineXMLPath = os.path.join(ConfigDataPath(), args.pipelinexmlpath)
            pipeline = pipelinemanager.PipelineManager.Load(PipelineXMLPath, pipelinename)
            pipeline.Execute(parser, buildArgs)

            print "Current Working Directory: " + os.getcwd()

    finally:
        OutStr = str(Timer)
        prettyoutput.Log(OutStr)
        try:
            OutputFile = open(os.path.join(args.volumepath, 'Timing.txt'), 'w')
            OutputFile.writelines(OutStr)
            OutputFile.close()
        except:
            prettyoutput.Log('Could not write timing.txt')


def SetupLogging(OutputPath):

    LogPath = os.path.join(OutputPath, 'Logs')

    if not os.path.exists(LogPath):
        os.makedirs(LogPath)

    formatter = logging.Formatter('%(levelname)s - %(name)s - %(message)s')

    logFileName = time.strftime('log-%M.%d.%y_%H.%M.txt', time.localtime())
    logFileName = os.path.join(LogPath, logFileName)
    errlogFileName = time.strftime('log-%M.%d.%y_%H.%M-Errors.txt', time.localtime())
    errlogFileName = os.path.join(LogPath, errlogFileName)
    logging.basicConfig(filename=logFileName, level='DEBUG', format='%(levelname)s - %(name)s - %(message)s')

    eh = logging.FileHandler(errlogFileName)
    eh.setLevel(logging.INFO)
    eh.setFormatter(formatter)

    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(formatter)

    logger = logging.getLogger()
    logger.addHandler(eh)
    logger.addHandler(ch)

    eh.setFormatter(formatter)


if __name__ == '__main__':

#    nornir_shared.Misc.RunWithProfiler('Execute()', "C:/Temp/profile.pr")

    parser = ProcessArgs()

    (args, extraargs) = parser.parse_known_args()

    SetupLogging(args.volumepath)

    Execute()