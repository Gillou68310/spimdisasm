#!/usr/bin/env python3

# SPDX-FileCopyrightText: © 2022 Decompollaborate
# SPDX-License-Identifier: MIT

from __future__ import annotations

from ... import common

from .. import symbols

from . import SectionBase


class SectionBss(SectionBase):
    def __init__(self, context: common.Context, vromStart: int, vromEnd: int, bssVramStart: int, bssVramEnd: int, filename: str, segmentVromStart: int, overlayCategory: str|None):
        super().__init__(context, vromStart, vromEnd, bssVramStart, filename, [], common.FileSectionType.Bss, segmentVromStart, overlayCategory)

        self.bssVramStart: int = bssVramStart
        self.bssVramEnd: int = bssVramEnd

        self.bssTotalSize: int = bssVramEnd - bssVramStart

        self.vram = bssVramStart

    @property
    def sizew(self) -> int:
        return self.bssTotalSize // 4

    def setVram(self, vram: int):
        super().setVram(vram)

        self.bssVramStart = vram
        self.bssVramEnd = vram + self.bssTotalSize

    def analyze(self):
        self.checkAndCreateFirstSymbol()

        # If something that could be a pointer found in data happens to be in the middle of this bss file's addresses space
        # Then consider it as a new bss variable
        for ptr in self.getAndPopPointerInDataReferencesRange(self.bssVramStart, self.bssVramEnd):
            # Check if the symbol already exists, in case the user has provided size
            contextSym = self.getSymbol(ptr, tryPlusOffset=True)
            if contextSym is None:
                self.addSymbol(ptr, sectionType=self.sectionType, isAutogenerated=True)


        offsetSymbolsInSection = self.context.offsetSymbols[common.FileSectionType.Bss]
        bssSymbolOffsets: set[int] = set(offsetSymbolsInSection.keys())

        for symbolVram, contextSym in self.getSymbolsRange(self.bssVramStart, self.bssVramEnd):
            # Mark every known symbol that happens to be in this address space as defined
            contextSym.sectionType = common.FileSectionType.Bss

            # Needs to move this to a list because the algorithm requires to check the size of a bss variable based on the next bss variable' vram
            bssSymbolOffsets.add(symbolVram - self.bssVramStart)

            # If the bss has an explicit size then produce an extra symbol after it, so the generated bss symbol uses the user-declared size
            if contextSym.size is not None:
                bssSymbolOffsets.add(symbolVram + contextSym.size - self.bssVramStart)


        sortedOffsets = sorted(bssSymbolOffsets)

        i = 0
        while i < len(sortedOffsets):
            symbolOffset = sortedOffsets[i]
            symbolVram = self.bssVramStart + symbolOffset

            # Calculate the space of the bss variable
            space = self.bssTotalSize - symbolOffset
            if i + 1 < len(sortedOffsets):
                nextSymbolOffset = sortedOffsets[i+1]
                if nextSymbolOffset <= self.bssTotalSize:
                    space = nextSymbolOffset - symbolOffset

            vrom = self.getVromOffset(symbolOffset)
            vromEnd = vrom + space
            sym = symbols.SymbolBss(self.context, vrom, vromEnd, symbolOffset + self.inFileOffset, symbolVram, space, self.segmentVromStart, self.overlayCategory)
            sym.parent = self
            sym.setCommentOffset(self.commentOffset)
            sym.analyze()
            self.symbolList.append(sym)

            self.symbolsVRams.add(symbolVram)

            i += 1
