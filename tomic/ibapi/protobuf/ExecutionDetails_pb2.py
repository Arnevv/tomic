# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# NO CHECKED-IN PROTOBUF GENCODE
# source: ExecutionDetails.proto
# Protobuf Python Version: 6.31.1
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import runtime_version as _runtime_version
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC,
    6,
    31,
    1,
    '',
    'ExecutionDetails.proto'
)
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


import Contract_pb2 as Contract__pb2
import Execution_pb2 as Execution__pb2


DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x16\x45xecutionDetails.proto\x12\x08protobuf\x1a\x0e\x43ontract.proto\x1a\x0f\x45xecution.proto\"\xa3\x01\n\x10\x45xecutionDetails\x12\x12\n\x05reqId\x18\x01 \x01(\x05H\x00\x88\x01\x01\x12)\n\x08\x63ontract\x18\x02 \x01(\x0b\x32\x12.protobuf.ContractH\x01\x88\x01\x01\x12+\n\texecution\x18\x03 \x01(\x0b\x32\x13.protobuf.ExecutionH\x02\x88\x01\x01\x42\x08\n\x06_reqIdB\x0b\n\t_contractB\x0c\n\n_executionB@\n\x16\x63om.ib.client.protobufB\x15\x45xecutionDetailsProto\xaa\x02\x0eIBApi.protobufb\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'ExecutionDetails_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
  _globals['DESCRIPTOR']._loaded_options = None
  _globals['DESCRIPTOR']._serialized_options = b'\n\026com.ib.client.protobufB\025ExecutionDetailsProto\252\002\016IBApi.protobuf'
  _globals['_EXECUTIONDETAILS']._serialized_start=70
  _globals['_EXECUTIONDETAILS']._serialized_end=233
# @@protoc_insertion_point(module_scope)
