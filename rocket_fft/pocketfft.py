import ctypes
from distutils.sysconfig import get_config_var
from functools import partial
from pathlib import Path

from llvmlite import ir
from llvmlite.binding import load_library_permanently
from numba import TypingError
from numba.core import types
from numba.core.cgutils import get_or_insert_function
from numba.extending import intrinsic
from numba.np.arrayobj import array_astype, make_array

# All integer variables passed to the C interface are by definition non-negative
# and we do not allow negative indexing on the C++ side. Therefore, we can always
# safely convert to an uint64.
# 'll_double' is only used for 'fct,' which is a double on the C++ side if the
# user passes an array with double precision data. Otherwise, it's a float32.
# Since 'fct' only loses precision if the array data is single precision, this
# is considered safe.
ll_uint64 = ir.IntType(64)
ll_double = ir.DoubleType()
ll_bool = ir.IntType(1)
ll_voidptr = ir.IntType(8).as_pointer()
ll_void = ir.VoidType()

uint64 = types.uint64
void = types.void


def load_pocketfft():
    search_path = Path(__file__).parent.parent
    ext_suffix = get_config_var("EXT_SUFFIX")
    ext_path = f"**/_pocketfft_numba{ext_suffix}"
    matches = search_path.glob(ext_path)
    libpath = str(next(matches))
    load_library_permanently(libpath)
    return ctypes.CDLL(libpath)


class Pocketfft:
    def __init__(self):
        self.dll = load_pocketfft()

    def _call_cmplx(fname, builder, args):
        fntype = ir.FunctionType(
            ll_void,
            (
                ll_uint64,  # ndim
                ll_voidptr,  # ain
                ll_voidptr,  # aout
                ll_voidptr,  # axes
                ll_bool,  # forward
                ll_double,  # fct
                ll_uint64,  # nthreads
            )
        )
        fn = get_or_insert_function(builder.module, fntype, fname)
        return builder.call(fn, args)

    c2c = partial(_call_cmplx, "numba_c2c")
    r2c = partial(_call_cmplx, "numba_r2c")
    c2r = partial(_call_cmplx, "numba_c2r")
    c2c_sym = partial(_call_cmplx, "numba_c2c_sym")

    def _call_real(fname, builder, args):
        fntype = ir.FunctionType(
            ll_void,
            (
                ll_uint64,  # ndim
                ll_voidptr,  # ain
                ll_voidptr,  # aout
                ll_voidptr,  # axes
                ll_uint64,  # type
                ll_double,  # fct
                ll_bool,  # ortho
                ll_uint64,  # nthreads
            )
        )
        fn = get_or_insert_function(builder.module, fntype, fname)
        return builder.call(fn, args)

    dct = partial(_call_real, "numba_dct")
    dst = partial(_call_real, "numba_dst")

    def _call_hartley(fname, builder, args):
        fntype = ir.FunctionType(
            ll_void,
            (
                ll_uint64,  # ndim
                ll_voidptr,  # ain
                ll_voidptr,  # aout
                ll_voidptr,  # axes
                ll_double,  # fct
                ll_uint64,  # nthreads
            )
        )
        fn = get_or_insert_function(builder.module, fntype, fname)
        return builder.call(fn, args)

    r2r_separable_hartley = partial(
        _call_hartley, "numba_r2r_separable_hartley")
    r2r_genuine_hartley = partial(_call_hartley, "numba_r2r_genuine_hartley")

    @staticmethod
    def r2r_fftpack(builder, args):
        fname = "numba_r2r_fftpack"
        fntype = ir.FunctionType(
            ll_void,
            (
                ll_uint64,  # ndim
                ll_voidptr,  # ain
                ll_voidptr,  # aout
                ll_voidptr,  # axes
                ll_bool,  # real2hermitian
                ll_bool,  # forward
                ll_double,  # fct
                ll_uint64,  # nthreads
            )
        )
        fn = get_or_insert_function(builder.module, fntype, fname)
        return builder.call(fn, args)

    @staticmethod
    def good_size(builder, args):
        fname = "numba_good_size"
        fntype = ir.FunctionType(
            ll_uint64,
            (
                ll_uint64,  # target
                ll_bool,  # real
            )
        )
        fn = get_or_insert_function(builder.module, fntype, fname)
        return builder.call(fn, args)


ll_pocketfft = Pocketfft()


def array_as_voidptr(context, builder, ary_t, ary):
    ary = make_array(ary_t)(context, builder, ary)
    ptr = ary._getpointer()
    return builder.bitcast(ptr, ll_voidptr)


class LLTypeConverter:
    def __init__(self, builder, int_type, float_type):
        self.builder = builder
        self.int_type = int_type
        self.float_type = float_type

    def __call__(self, *values):
        values = list(values)
        for index, value in enumerate(values):
            if isinstance(value.type, ir.IntType) and (value.type.width != 1):
                values[index] = self.builder.zext(value, self.int_type)
            elif isinstance(value.type, ir.FloatType):
                values[index] = self.builder.fpext(value, self.float_type)
        return values


_tmpl = """
def _(typingctx, ain, aout, axes, {0}):
    if ain.ndim != aout.ndim:
        raise TypingError("Input and output array must have"
                          "the same number of dimensions")

    if axes.ndim != 1:
        raise TypingError("Axes must be a one-dimensional array")

    copy_axes = not (isinstance(axes.dtype, types.Integer)
                     and (axes.layout in ("C", "F"))
                     and (axes.dtype.bitwidth == 64))

    def codegen(context, builder, sig, args):
        ain, aout, axes, *rest = args
        ain_t, aout_t, axes_t, *_ = sig.args

        if copy_axes:
            new_t = types.Array(uint64, ndim=1, layout="C")
            sig = new_t(axes_t, uint64)
            args = (axes, uint64)
            axes = array_astype(context, builder, sig, args)
            axes_t = new_t

        ndim = ll_uint64(ain_t.ndim)
        ain_ptr = array_as_voidptr(context, builder, ain_t, ain)
        aout_ptr = array_as_voidptr(context, builder, aout_t, aout)
        ax_ptr = array_as_voidptr(context, builder, axes_t, axes)

        ll_convert = LLTypeConverter(builder, ll_uint64, ll_double)
        args = ll_convert(ndim, ain_ptr, aout_ptr, ax_ptr, *rest)
        ll_pocketfft.{1}(builder, (args))

    sig = void(ain, aout, axes, {0})
    return sig, codegen
"""


class Builder:
    def __init__(self, *extra_args):
        self.extra_args = ", ".join(extra_args)

    def __call__(self, fname):
        src = _tmpl.format(self.extra_args, fname)
        exec(src)
        func = locals()["_"]
        func.__name__ = fname
        return intrinsic(func)


cmplx_builder = Builder("forward", "fct", "nthreads")
numba_c2c = cmplx_builder("c2c")
numba_r2c = cmplx_builder("r2c")
numba_c2r = cmplx_builder("c2r")
numba_c2c_sym = cmplx_builder("c2c_sym")

real_builder = Builder("type", "fct", "ortho", "nthreads")
numba_dst = real_builder("dst")
numba_dct = real_builder("dct")

hartley_builder = Builder("fct", "nthreads")
numba_r2r_separable_hartley = hartley_builder("r2r_separable_hartley")
numba_r2r_genuine_hartley = hartley_builder("r2r_genuine_hartley")

fftpack_builder = Builder("real2hermitian", "forward", "fct", "nthreads")
numba_r2r_fftpack = fftpack_builder("r2r_fftpack")


@intrinsic
def numba_good_size(typingctx, n, real):
    if not isinstance(n, (types.Integer, types.Boolean)):
        raise TypingError("The first argument 'n' must be an integer")
    if not isinstance(real, (types.Integer, types.Boolean)):
        raise TypingError("The second argument 'real' must be a boolean")
    
    def codegen(context, builder, sig, args):
        n, real = args 
        n = builder.zext(n, ll_uint64)
        real = builder.trunc(real, ll_bool)
        ret = ll_pocketfft.good_size(builder, (n, real))
        return ret

    sig = uint64(n, real)
    return sig, codegen
