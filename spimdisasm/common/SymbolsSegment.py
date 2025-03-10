#!/usr/bin/env python3

# SPDX-FileCopyrightText: © 2022 Decompollaborate
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ast
from typing import TextIO, Generator
from pathlib import Path

from . import Utils
from .SortedDict import SortedDict
from .GlobalConfig import GlobalConfig
from .FileSectionType import FileSectionType
from .ContextSymbols import SymbolSpecialType, ContextSymbol


class SymbolsSegment:
    def __init__(self, vromStart: int|None, vromEnd: int|None, vramStart: int, vramEnd: int, overlayCategory: str|None=None):
        assert vramStart < vramEnd
        if vromStart is not None and vromEnd is not None:
            assert vromStart < vromEnd

        self.vromStart: int|None = vromStart
        self.vromEnd: int|None = vromEnd

        self.vramStart: int = vramStart
        self.vramEnd: int = vramEnd

        self.overlayCategory: str|None = overlayCategory

        self.symbols: SortedDict[ContextSymbol] = SortedDict()

        self.constants: dict[int, ContextSymbol] = dict()

        self.newPointersInData: SortedDict[int] = SortedDict()
        "Stuff that looks like pointers, found referenced by data"

        self.loPatches: dict[int, int] = dict()
        "key: address of %lo, value: symbol's vram to use instead"

        self.dataSymbolsWithReferencesWithAddends: set[int] = set()
        "Contains the address of data symbols which are allowed to have references to other symbols with addends"

        self.dataReferencingConstants: set[int] = set()
        "Set of addresses of data symbols which are allowed to reference named constants"

        self._isTheUnknownSegment: bool = False


    @property
    def vromSize(self) -> int|None:
        if self.vromStart is None:
            return None
        if self.vromEnd is None:
            return None
        return self.vromEnd - self.vromStart

    @property
    def vramSize(self) -> int:
        return self.vramEnd - self.vramStart


    def isVromInRange(self, vrom: int) -> bool:
        if self.vromStart is None:
            return False
        if self.vromEnd is None:
            return False
        return self.vromStart <= vrom < self.vromEnd

    def isVramInRange(self, vram: int) -> bool:
        return self.vramStart <= vram < self.vramEnd

    def changeRanges(self, vromStart: int, vromEnd: int, vramStart: int, vramEnd: int) -> None:
        assert vromStart < vromEnd
        assert vramStart < vramEnd

        self.vromStart = vromStart
        self.vromEnd = vromEnd

        self.vramStart = vramStart
        self.vramEnd = vramEnd


    def vromToVram(self, vrom: int) -> int|None:
        if self.vromStart is None:
            return None
        return vrom - self.vromStart + self.vramStart


    def addSymbol(self, address: int, sectionType: FileSectionType=FileSectionType.Unknown, isAutogenerated: bool=False, vromAddress: int|None=None) -> ContextSymbol:
        contextSym = self.symbols.get(address, None)
        if contextSym is None:
            contextSym = ContextSymbol(address)
            contextSym.isAutogenerated = isAutogenerated
            contextSym.sectionType = sectionType
            contextSym.overlayCategory = self.overlayCategory
            self.symbols[address] = contextSym

        if contextSym.sectionType == FileSectionType.Unknown:
            contextSym.sectionType = sectionType

        if contextSym.vromAddress is None and vromAddress is not None:
            contextSym.vromAddress = vromAddress

        if self.vromStart is None or self.vromEnd is None or self._isTheUnknownSegment:
            contextSym.unknownSegment = True

        return contextSym

    def addFunction(self, address: int, isAutogenerated: bool=False, vromAddress: int|None=None) -> ContextSymbol:
        contextSym = self.addSymbol(address, sectionType=FileSectionType.Text, isAutogenerated=isAutogenerated, vromAddress=vromAddress)
        if contextSym.type != SymbolSpecialType.jumptablelabel:
            contextSym.type = SymbolSpecialType.function
        contextSym.sectionType = FileSectionType.Text
        return contextSym

    def addBranchLabel(self, address: int, isAutogenerated: bool=False, vromAddress: int|None=None) -> ContextSymbol:
        contextSym = self.addSymbol(address, sectionType=FileSectionType.Text, isAutogenerated=isAutogenerated, vromAddress=vromAddress)
        if contextSym.type != SymbolSpecialType.jumptablelabel and contextSym.type != SymbolSpecialType.function:
            contextSym.type = SymbolSpecialType.branchlabel
        return contextSym

    def addJumpTable(self, address: int, isAutogenerated: bool=False, vromAddress: int|None=None) -> ContextSymbol:
        contextSym = self.addSymbol(address, sectionType=FileSectionType.Rodata, isAutogenerated=isAutogenerated, vromAddress=vromAddress)
        if contextSym.type != SymbolSpecialType.function:
            contextSym.type = SymbolSpecialType.jumptable
        return contextSym

    def addJumpTableLabel(self, address: int, isAutogenerated: bool=False, vromAddress: int|None=None) -> ContextSymbol:
        contextSym = self.addSymbol(address, sectionType=FileSectionType.Text, isAutogenerated=isAutogenerated, vromAddress=vromAddress)
        contextSym.type = SymbolSpecialType.jumptablelabel
        contextSym.sectionType = FileSectionType.Text
        return contextSym


    def addConstant(self, constantValue: int, name: str) -> ContextSymbol:
        if constantValue not in self.constants:
            contextSym = ContextSymbol(constantValue)
            contextSym.name = name
            contextSym.type = SymbolSpecialType.constant
            self.constants[constantValue] = contextSym
            return contextSym
        return self.constants[constantValue]


    def getSymbol(self, address: int, tryPlusOffset: bool = True, checkUpperLimit: bool = True) -> ContextSymbol|None:
        "Searches symbol or a symbol with an addend if `tryPlusOffset` is True"
        if GlobalConfig.PRODUCE_SYMBOLS_PLUS_OFFSET and tryPlusOffset:
            pair = self.symbols.getKeyRight(address, inclusive=True)
            if pair is None:
                return None

            symVram, contextSym = pair
            if checkUpperLimit and address >= symVram + contextSym.getSize():
                return None
            return contextSym

        return self.symbols.get(address, None)

    def getSymbolsRange(self, addressStart: int, addressEnd: int) -> Generator[tuple[int, ContextSymbol], None, None]:
        return self.symbols.getRange(addressStart, addressEnd, startInclusive=True, endInclusive=False)

    def getConstant(self, constantValue: int) -> ContextSymbol|None:
        return self.constants.get(constantValue, None)


    def addPointerInDataReference(self, pointer: int) -> None:
        self.newPointersInData[pointer] = pointer

    def popPointerInDataReference(self, pointer: int) -> int|None:
        return self.newPointersInData.pop(pointer, None)

    def getAndPopPointerInDataReferencesRange(self, low: int, high: int) -> Generator[int, None, None]:
        for key, _ in self.newPointersInData.getRangeAndPop(low, high, startInclusive=True, endInclusive=False):
            yield key


    def getLoPatch(self, loInstrVram: int|None) -> int|None:
        if loInstrVram is None:
            return None
        return self.loPatches.get(loInstrVram, None)


    def saveContextToFile(self, f: TextIO):
        f.write(f"category,{ContextSymbol.getCsvHeader()}\n")

        for address in self.symbols:
            f.write(f"symbol,{self.symbols[address].toCsv()}\n")

        for address, constant in self.constants.items():
            f.write(f"constants,{constant.toCsv()}\n")

        for address in self.newPointersInData:
            f.write(f"new_pointer_in_data,0x{address:08X}\n")


    N64LibultraSyms: dict[int, tuple[str, str, int]] = {
        0x800001A0: ("leoBootID",      "u32", 0x4),
        0x80000300: ("osTvType",       "u32", 0x4),
        0x80000304: ("osRomType",      "u32", 0x4),
        0x80000308: ("osRomBase",      "u32", 0x4),
        0x8000030C: ("osResetType",    "u32", 0x4),
        0x80000310: ("osCicId",        "u32", 0x4),
        0x80000314: ("osVersion",      "u32", 0x4),
        0x80000318: ("osMemSize",      "u32", 0x4),
        0x8000031C: ("osAppNmiBuffer", "u8",  0x40),
    }

    N64HardwareRegs = {
        # Signal Processor Registers
        0xA4040000: "SP_MEM_ADDR_REG",
        0xA4040004: "SP_DRAM_ADDR_REG",
        0xA4040008: "SP_RD_LEN_REG",
        0xA404000C: "SP_WR_LEN_REG",
        0xA4040010: "SP_STATUS_REG",
        0xA4040014: "SP_DMA_FULL_REG",
        0xA4040018: "SP_DMA_BUSY_REG",
        0xA404001C: "SP_SEMAPHORE_REG",

        0xA4080000: "SP_PC",

        # Display Processor Command Registers / Rasterizer Interface
        0xA4100000: "DPC_START_REG",
        0xA4100004: "DPC_END_REG",
        0xA4100008: "DPC_CURRENT_REG",
        0xA410000C: "DPC_STATUS_REG",
        0xA4100010: "DPC_CLOCK_REG",
        0xA4100014: "DPC_BUFBUSY_REG",
        0xA4100018: "DPC_PIPEBUSY_REG",
        0xA410001C: "DPC_TMEM_REG",

        # Display Processor Span Registers
        0xA4200000: "DPS_TBIST_REG", # DPS_TBIST_REG / DP_TMEM_BIST
        0xA4200004: "DPS_TEST_MODE_REG",
        0xA4200008: "DPS_BUFTEST_ADDR_REG",
        0xA420000C: "DPS_BUFTEST_DATA_REG",

        # MIPS Interface Registers
        0xA4300000: "MI_MODE_REG", # MI_MODE_REG / MI_INIT_MODE_REG
        0xA4300004: "MI_VERSION_REG",
        0xA4300008: "MI_INTR_REG",
        0xA430000C: "MI_INTR_MASK_REG",

        # Video Interface Registers
        0xA4400000: "VI_STATUS_REG", # VI_STATUS_REG / VI_CONTROL_REG
        0xA4400004: "VI_DRAM_ADDR_REG", # VI_DRAM_ADDR_REG / VI_ORIGIN_REG
        0xA4400008: "VI_WIDTH_REG",
        0xA440000C: "VI_INTR_REG",
        0xA4400010: "VI_CURRENT_REG",
        0xA4400014: "VI_BURST_REG", # VI_BURST_REG / VI_TIMING_REG
        0xA4400018: "VI_V_SYNC_REG",
        0xA440001C: "VI_H_SYNC_REG",
        0xA4400020: "VI_LEAP_REG",
        0xA4400024: "VI_H_START_REG",
        0xA4400028: "VI_V_START_REG",
        0xA440002C: "VI_V_BURST_REG",
        0xA4400030: "VI_X_SCALE_REG",
        0xA4400034: "VI_Y_SCALE_REG",

        # Audio Interface Registers
        0xA4500000: "AI_DRAM_ADDR_REG",
        0xA4500004: "AI_LEN_REG",
        0xA4500008: "AI_CONTROL_REG",
        0xA450000C: "AI_STATUS_REG",
        0xA4500010: "AI_DACRATE_REG",
        0xA4500014: "AI_BITRATE_REG",

        # Peripheral/Parallel Interface Registers
        0xA4600000: "PI_DRAM_ADDR_REG",
        0xA4600004: "PI_CART_ADDR_REG",
        0xA4600005: "D_A4600005", # TODO: figure out its name
        0xA4600006: "D_A4600006", # TODO: figure out its name
        0xA4600007: "D_A4600007", # TODO: figure out its name
        0xA4600008: "PI_RD_LEN_REG",
        0xA460000C: "PI_WR_LEN_REG",
        0xA4600010: "PI_STATUS_REG",
        0xA4600014: "PI_BSD_DOM1_LAT_REG", # PI dom1 latency
        0xA4600018: "PI_BSD_DOM1_PWD_REG", # PI dom1 pulse width
        0xA460001C: "PI_BSD_DOM1_PGS_REG", # PI dom1 page size
        0xA4600020: "PI_BSD_DOM1_RLS_REG", # PI dom1 release
        0xA4600024: "PI_BSD_DOM2_LAT_REG", # PI dom2 latency
        0xA4600028: "PI_BSD_DOM2_LWD_REG", # PI dom2 pulse width
        0xA460002C: "PI_BSD_DOM2_PGS_REG", # PI dom2 page size
        0xA4600030: "PI_BSD_DOM2_RLS_REG", # PI dom2 release

        # RDRAM Interface Registers
        0xA4700000: "RI_MODE_REG",
        0xA4700004: "RI_CONFIG_REG",
        0xA4700008: "RI_CURRENT_LOAD_REG",
        0xA470000C: "RI_SELECT_REG",
        0xA4700010: "RI_REFRESH_REG",
        0xA4700014: "RI_LATENCY_REG",
        0xA4700018: "RI_RERROR_REG",
        0xA470001C: "RI_WERROR_REG",

        # Serial Interface Registers
        0xA4800000: "SI_DRAM_ADDR_REG",
        0xA4800004: "SI_PIF_ADDR_RD64B_REG",
        0xA4800008: "D_A4800008", # reserved
        0xA480000C: "D_A480000C", # reserved
        0xA4800010: "SI_PIF_ADDR_WR64B_REG",
        0xA4800014: "D_A4800014", # reserved
        0xA4800018: "SI_STATUS_REG",
    }
    "N64 OS hardware registers"


    def fillLibultraSymbols(self):
        for vram, (name, type, size) in self.N64LibultraSyms.items():
            contextSym = self.addSymbol(vram)
            contextSym.name = name
            contextSym.type = type
            contextSym.size = size
            contextSym.isDefined = True
            contextSym.isUserDeclared = True

    def fillHardwareRegs(self, useRealNames: bool=False):
        for vram, name in self.N64HardwareRegs.items():
            nameToUse = None
            if useRealNames:
                nameToUse = name
            contextSym = self.addSymbol(vram)
            contextSym.name = nameToUse
            contextSym.type = SymbolSpecialType.hardwarereg
            contextSym.size = 4
            contextSym.isDefined = True
            contextSym.isUserDeclared = True


    def readMMAddressMaps(self, functionsPath: str, variablesPath: str):
        with open(functionsPath) as infile:
            functions_ast = ast.literal_eval(infile.read())

        for vram, funcData in functions_ast.items():
            funcName = funcData[0]
            contextSym = self.addFunction(vram, funcName)
            contextSym.isUserDeclared = True

        with open(variablesPath) as infile:
            variables_ast = ast.literal_eval(infile.read())

        for vram, varData in variables_ast.items():
            varName, varType, varArrayInfo, varSize = varData
            if varType == "":
                varType = None

            contextSym = self.addSymbol(vram, varName)
            contextSym.type = varType
            contextSym.size = varSize
            contextSym.isUserDeclared = True

    def readVariablesCsv(self, filepath: Path):
        if not filepath.exists():
            return

        variables_file = Utils.readCsv(filepath)
        for row in variables_file:
            if len(row) == 0:
                continue

            varType: SymbolSpecialType|str|None
            vramStr, varName, varType, varSizeStr = row
            if vramStr == "-":
                continue

            vram = int(vramStr, 16)
            varSize = int(varSizeStr, 16)
            if varType == "":
                varType = None

            specialType = SymbolSpecialType.fromStr(varType)
            if specialType is not None:
                varType = specialType
                if specialType == SymbolSpecialType.function:
                    contextSym = self.addFunction(vram)
                elif specialType == SymbolSpecialType.branchlabel:
                    contextSym = self.addBranchLabel(vram)
                elif specialType == SymbolSpecialType.jumptable:
                    contextSym = self.addJumpTable(vram)
                elif specialType == SymbolSpecialType.jumptablelabel:
                    contextSym = self.addJumpTableLabel(vram)
                elif specialType == SymbolSpecialType.hardwarereg:
                    contextSym = self.addSymbol(vram)
                else:
                    contextSym = self.addSymbol(vram)
            else:
                contextSym = self.addSymbol(vram)

            contextSym.name = varName
            contextSym.type = varType
            contextSym.size = varSize
            contextSym.isUserDeclared = True

    def readFunctionsCsv(self, filepath: Path):
        if not filepath.exists():
            return

        functions_file = Utils.readCsv(filepath)
        for row in functions_file:
            if len(row) == 0:
                continue

            vramStr, funcName = row
            if vramStr == "-":
                continue

            vram = int(vramStr, 16)
            contextSym = self.addFunction(vram)
            contextSym.name = funcName
            contextSym.isUserDeclared = True

    def readConstantsCsv(self, filepath: Path):
        if not filepath.exists():
            return

        constants_file = Utils.readCsv(filepath)
        for row in constants_file:
            if len(row) == 0:
                continue

            constantValueStr, constantName = row
            if constantValueStr == "-":
                continue

            constantValue = int(constantValueStr, 16)
            contextSym = self.addConstant(constantValue, constantName)
            contextSym.isUserDeclared = True
