#!/usr/bin/env python3

# SPDX-FileCopyrightText: © 2022 Decompollaborate
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
from pathlib import Path

from . import Utils
from .FileSectionType import FileSectionType
from .ContextSymbols import ContextRelocInfo
from .SymbolsSegment import SymbolsSegment
from .GlobalOffsetTable import GlobalOffsetTable


class Context:
    N64DefaultBanned = {
        0x7FFFFFE0, # osInvalICache
        0x7FFFFFF0, # osInvalDCache, osWritebackDCache, osWritebackDCacheAll
        0x7FFFFFFF,
        0x80000010,
        0x80000020,
    }

    def __init__(self):
        # Arbitrary initial range
        self.globalSegment = SymbolsSegment(0x0, 0x1000, 0x80000000, 0x80001000, overlayCategory=None)
        # For symbols that we don't know where they come from
        self.unknownSegment = SymbolsSegment(None, None, 0x00000000, 0xFFFFFFFF, overlayCategory=None)
        self._isTheUnknownSegment = True

        self.overlaySegments: dict[str, dict[int, SymbolsSegment]] = dict()
        "Outer key is overlay type, inner key is the vrom of the overlay's segment"

        self.totalVramStart: int = self.globalSegment.vramStart
        self.totalVramEnd: int = self.globalSegment.vramEnd
        self._defaultVramRanges: bool = True

        # Stuff that looks like pointers, but the disassembler shouldn't count it as a pointer
        self.bannedSymbols: set[int] = set()

        self.relocInfosPerSection: dict[FileSectionType, dict[int, ContextRelocInfo]] = {
            FileSectionType.Text: dict(),
            FileSectionType.Data: dict(),
            FileSectionType.Rodata: dict(),
            FileSectionType.Bss: dict(),
        }

        self.got: GlobalOffsetTable = GlobalOffsetTable()


    def changeGlobalSegmentRanges(self, vromStart: int, vromEnd: int, vramStart: int, vramEnd: int):
        self.globalSegment.changeRanges(vromStart, vromEnd, vramStart, vramEnd)
        if self._defaultVramRanges:
            self.totalVramStart = vramStart
            self.totalVramEnd = vramEnd
            self._defaultVramRanges = False
        if vramStart < self.totalVramStart:
            self.totalVramStart = vramStart
        if vramEnd > self.totalVramEnd:
            self.totalVramEnd = vramEnd

    def addOverlaySegment(self, overlayCategory: str, segmentVromStart: int, segmentVromEnd: int, segmentVramStart: int, segmentVramEnd: int) -> SymbolsSegment:
        if overlayCategory not in self.overlaySegments:
            self.overlaySegments[overlayCategory] = dict()
        segment = SymbolsSegment(segmentVromStart, segmentVromEnd, segmentVramStart, segmentVramEnd, overlayCategory=overlayCategory)
        self.overlaySegments[overlayCategory][segmentVromStart] = segment

        if self._defaultVramRanges:
            self.totalVramStart = segmentVramStart
            self.totalVramEnd = segmentVramEnd
            self._defaultVramRanges = False
        if segmentVramStart < self.totalVramStart:
            self.totalVramStart = segmentVramStart
        if segmentVramEnd > self.totalVramEnd:
            self.totalVramEnd = segmentVramEnd

        return segment


    def getRelocInfo(self, vram: int, sectionType: FileSectionType) -> ContextRelocInfo|None:
        relocsInSection = self.relocInfosPerSection.get(sectionType)
        if relocsInSection is not None:
            return relocsInSection.get(vram)
        return None

    def doesSectionHasRelocs(self, sectionType: FileSectionType) -> bool:
        return len(self.relocInfosPerSection[sectionType]) != 0


    def initGotTable(self, pltGot: int, localsTable: list[int], globalsTable: list[int]):
        self.got.initTables(pltGot, localsTable, globalsTable)

        for gotEntry in self.got.globalsTable:
            gotEntry.contextSym = self.globalSegment.addSymbol(gotEntry.address)
            gotEntry.contextSym.isUserDeclared = True
            gotEntry.contextSym.isGotGlobal = True


    def fillDefaultBannedSymbols(self):
        self.bannedSymbols |= self.N64DefaultBanned


    def saveContextToFile(self, contextPath: Path):
        with contextPath.open("w") as f:
            self.globalSegment.saveContextToFile(f)

        # unknownPath = contextPath.with_stem(f"{contextPath.stem}_unksegment")
        unknownPath = contextPath.with_name(f"{contextPath.stem}_unksegment" + contextPath.suffix)
        with unknownPath.open("w") as f:
            self.unknownSegment.saveContextToFile(f)

        for overlayCategory, segmentsPerVrom in self.overlaySegments.items():
            for segmentVrom, overlaySegment in segmentsPerVrom.items():

                # ovlPath = contextPath.with_stem(f"{contextPath.stem}_{overlayCategory}_{segmentVrom:06X}")
                ovlPath = contextPath.with_name(f"{contextPath.stem}_{overlayCategory}_{segmentVrom:06X}" + contextPath.suffix)
                with ovlPath.open("w") as f:
                    overlaySegment.saveContextToFile(f)


    @staticmethod
    def addParametersToArgParse(parser: argparse.ArgumentParser):
        contextParser = parser.add_argument_group("Context configuration")

        contextParser.add_argument("--save-context", help="Saves the context to a file", metavar="FILENAME")


        csvConfig = parser.add_argument_group("Context .csv input files")

        csvConfig.add_argument("--functions", help="Path to a functions csv", action="append")
        csvConfig.add_argument("--variables", help="Path to a variables csv", action="append")
        csvConfig.add_argument("--constants", help="Path to a constants csv", action="append")


        symbolsConfig = parser.add_argument_group("Context default symbols configuration")

        symbolsConfig.add_argument("--default-banned", help="Toggles filling the list of default banned symbols. Defaults to True", action=Utils.BooleanOptionalAction)
        symbolsConfig.add_argument("--libultra-syms", help="Toggles using the built-in libultra symbols. Defaults to True", action=Utils.BooleanOptionalAction)
        symbolsConfig.add_argument("--hardware-regs", help="Toggles using the built-in hardware registers symbols. Defaults to True", action=Utils.BooleanOptionalAction)
        symbolsConfig.add_argument("--named-hardware-regs", help="Use actual names for the hardware registers", action=Utils.BooleanOptionalAction)


    def parseArgs(self, args: argparse.Namespace):
        if args.default_banned != False:
            self.fillDefaultBannedSymbols()
        if args.libultra_syms != False:
            self.globalSegment.fillLibultraSymbols()
        if args.hardware_regs != False:
            self.globalSegment.fillHardwareRegs(args.named_hardware_regs)

        if args.functions is not None:
            for funcsPath in args.functions:
                self.globalSegment.readFunctionsCsv(Path(funcsPath))
        if args.variables is not None:
            for varsPath in args.variables:
                self.globalSegment.readVariablesCsv(Path(varsPath))
        if args.constants is not None:
            for constantsPath in args.constants:
                self.globalSegment.readConstantsCsv(Path(constantsPath))
