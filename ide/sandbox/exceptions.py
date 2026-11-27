class UnsafeOperationDetected(Exception):
    """Levantada por verify_program()/run_program() ante cualquier
    operacion en las deny-lists de vm.sandbox_interp.iesy."""
    pass
