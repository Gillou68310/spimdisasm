#!/usr/bin/env python3

# SPDX-FileCopyrightText: © 2022 Decompollaborate
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
from pathlib import Path

from .. import common
from .. import mips
from .. import frontendCommon as fec


def getArgsParser() -> argparse.ArgumentParser:
    description = "General purpose N64-mips disassembler"
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument("binary", help="Path to input binary")
    parser.add_argument("output", help="Path to output. Use '-' to print to stdout instead")

    parser.add_argument("--data-output", help="Path to output the data and rodata disassembly")

    parser_singleFile = parser.add_argument_group("Single file disassembly options")

    parser_singleFile.add_argument("--start", help="Raw offset of the input binary file to start disassembling. Expects an hex value", default="0")
    parser_singleFile.add_argument("--end", help="Offset end of the input binary file to start disassembling. Expects an hex value",  default="0xFFFFFF")
    parser_singleFile.add_argument("--vram", help="Set the VRAM address. Expects an hex value", default="0x0")

    parser_singleFile.add_argument("--disasm-rsp", help=f"Experimental. Disassemble this file using rsp ABI instructions. Warning: In its current state the generated asm may not be assemblable to a matching binary. Defaults to False", action="store_true")

    parser.add_argument("--file-splits", help="Path to a file splits csv")

    parser.add_argument("--split-functions", help="Enables the function and rodata splitter. Expects a path to place the splited functions", metavar="PATH")

    parser.add_argument("--nuke-pointers", help="Use every technique available to remove pointers", action=common.Utils.BooleanOptionalAction)
    parser.add_argument("--ignore-words", help="A space separated list of hex numbers. Any word differences which starts in any of the provided arguments will be ignored. Max value: FF. Only works when --nuke-pointers is passed", action="extend", nargs="+")

    parser.add_argument("--write-binary", help=f"Produce a binary from the processed file. Defaults to {common.GlobalConfig.WRITE_BINARY}", action=common.Utils.BooleanOptionalAction)


    common.Context.addParametersToArgParse(parser)

    common.GlobalConfig.addParametersToArgParse(parser)

    mips.InstructionConfig.addParametersToArgParse(parser)

    return parser

def applyArgs(args: argparse.Namespace) -> None:
    mips.InstructionConfig.parseArgs(args)

    common.GlobalConfig.parseArgs(args)

    common.GlobalConfig.REMOVE_POINTERS = args.nuke_pointers
    common.GlobalConfig.IGNORE_BRANCHES = args.nuke_pointers
    if args.nuke_pointers:
        common.GlobalConfig.IGNORE_WORD_LIST.add(0x80)
        if args.ignore_words:
            for upperByte in args.ignore_words:
                common.GlobalConfig.IGNORE_WORD_LIST.add(int(upperByte, 16))
    if args.write_binary is not None:
        common.GlobalConfig.WRITE_BINARY = args.write_binary

def applyGlobalConfigurations() -> None:
    common.GlobalConfig.PRODUCE_SYMBOLS_PLUS_OFFSET = True
    common.GlobalConfig.TRUST_USER_FUNCTIONS = True

def getSplits(fileSplitsPath: Path|None, vromStart: int, vromEnd: int, fileVram: int, disasmRsp: bool) -> common.FileSplitFormat:
    splits = common.FileSplitFormat()
    if fileSplitsPath is not None:
        splits.readCsvFile(fileSplitsPath)

    if len(splits) == 0:
        if fileSplitsPath is not None:
            common.Utils.eprint("Warning: Tried to use file split mode, but passed csv splits file was empty")
            common.Utils.eprint("\t Using single-file mode instead")

        endVram = fileVram + vromEnd - vromStart

        splitEntry = common.FileSplitEntry(vromStart, fileVram, "", common.FileSectionType.Text, vromEnd, False, disasmRsp)
        splits.append(splitEntry)

        splits.appendEndSection(vromEnd, endVram)

    return splits


def changeGlobalSegmentRanges(context: common.Context, processedFiles: dict[common.FileSectionType, list[mips.sections.SectionBase]], fileSize: int, fileVram: int) -> None:
    highestVromEnd = fileSize
    lowestVramStart = 0x80000000
    highestVramEnd = lowestVramStart + highestVromEnd
    if fileVram != 0:
        lowestVramStart = fileVram
        highestVramEnd = (fileVram & 0xF0000000) + highestVromEnd

    for filesInSection in processedFiles.values():
        for mipsSection in filesInSection:
            if lowestVramStart is None or mipsSection.vram < lowestVramStart:
                lowestVramStart = mipsSection.vram
            if highestVramEnd is None or mipsSection.vramEnd > highestVramEnd:
                highestVramEnd = mipsSection.vramEnd

    if lowestVramStart is None:
        lowestVramStart = 0x0
    if highestVramEnd is None:
        highestVramEnd = 0xFFFFFFFF
    context.changeGlobalSegmentRanges(0, highestVromEnd, lowestVramStart, highestVramEnd)
    return


def disassemblerMain():
    args = getArgsParser().parse_args()
    applyArgs(args)

    applyGlobalConfigurations()

    context = common.Context()
    context.parseArgs(args)

    inputPath = Path(args.binary)
    array_of_bytes = common.Utils.readFileAsBytearray(inputPath)

    fileSplitsPath = None
    if args.file_splits is not None:
        fileSplitsPath = Path(args.file_splits)
    vromStart = int(args.start, 16)
    vromEnd = int(args.end, 16)
    if vromEnd == 0xFFFFFF:
        vromEnd = len(array_of_bytes)
    fileVram = int(args.vram, 16)
    splits = getSplits(fileSplitsPath, vromStart, vromEnd, fileVram, args.disasm_rsp)

    textOutput = Path(args.output)
    if args.data_output is None:
        dataOutput = textOutput
    else:
        dataOutput = Path(args.data_output)

    processedFiles, processedFilesOutputPaths = fec.FrontendUtilities.getSplittedSections(context, splits, array_of_bytes, inputPath, textOutput, dataOutput)
    changeGlobalSegmentRanges(context, processedFiles, len(array_of_bytes), int(args.vram, 16))

    processedFilesCount = 0
    for sect in processedFiles.values():
        processedFilesCount += len(sect)

    progressCallback: fec.FrontendUtilities.ProgressCallbackType

    progressCallback = fec.FrontendUtilities.progressCallback_analyzeProcessedFiles
    fec.FrontendUtilities.analyzeProcessedFiles(processedFiles, processedFilesOutputPaths, processedFilesCount, progressCallback)

    if args.nuke_pointers:
        common.Utils.printVerbose("Nuking pointers...")
        progressCallback = fec.FrontendUtilities.progressCallback_nukePointers
        fec.FrontendUtilities.nukePointers(processedFiles, processedFilesOutputPaths, processedFilesCount, progressCallback)

    progressCallback = fec.FrontendUtilities.progressCallback_writeProcessedFiles
    fec.FrontendUtilities.writeProcessedFiles(processedFiles, processedFilesOutputPaths, processedFilesCount, progressCallback)

    if args.split_functions is not None:
        common.Utils.printVerbose("\nSpliting functions...")
        progressCallback = fec.FrontendUtilities.progressCallback_migrateFunctions
        fec.FrontendUtilities.migrateFunctions(processedFiles, Path(args.split_functions), progressCallback)

    if args.save_context is not None:
        contextPath = Path(args.save_context)
        contextPath.parent.mkdir(parents=True, exist_ok=True)
        context.saveContextToFile(contextPath)

    common.Utils.printQuietless(500*" " + "\r", end="")
    common.Utils.printQuietless(f"Done: {args.binary}")

    common.Utils.printVerbose()
    common.Utils.printVerbose("Disassembling complete!")
    common.Utils.printVerbose("Goodbye.")
