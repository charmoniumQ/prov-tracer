use proc_macro::TokenStream;
use proc_macro2::Span;
use quote::quote;
use syn::parse_quote;
use syn::{parse_macro_input, Data, DeriveInput, Fields, Ident, Type};

mod pygen;

// TODO: return compiler error instead of panicking on error
#[proc_macro_derive(MakeRustOp)]
pub fn make_rust_op(input: TokenStream) -> TokenStream {
    let original_struct = parse_macro_input!(input as DeriveInput);
    let DeriveInput { data, ident, .. } = original_struct.clone();

    match data {
        Data::Struct(data_struct) => {
            let fields = match data_struct.fields {
                Fields::Named(x) => x,
                _ => unimplemented!("unnamed and unit structs not implemented"),
            };

            let pairs = fields
                .named
                .iter()
                .filter_map(|x| {
                    let ident = x.ident.as_ref().unwrap();
                    if ident.to_string().starts_with("__") {
                        return None;
                    }
                    Some((ident, convert_bindgen_type(&x.ty)))
                })
                .collect::<Vec<(_, _)>>();

            let field_idents = pairs.iter().map(|x| x.0).collect::<Vec<_>>();

            let field_types = pairs.into_iter().map(|x| x.1).collect::<Vec<_>>();

            let new_name = Ident::new(
                ident
                    .to_string()
                    .strip_prefix("C_")
                    .expect("struct name doesn't start with 'C_'"),
                Span::call_site(),
            );

            // This is rather bad macro hygiene, but this macro is only intend for probe_frontend's
            // op struct generation, so we're playing a little fast-n'-loose with scoping.
            quote! {
                #[derive(Debug, Clone, Serialize, Deserialize, MakePyDataclass)]
                pub struct #new_name {
                    #(pub #field_idents: #field_types,)*
                }

                impl FfiFrom<#ident> for #new_name {
                    fn ffi_from(value: &#ident, ctx: &ArenaContext) -> Result<Self> {
                        Ok(Self {
                            #(
                            #field_idents: value.#field_idents
                                .ffi_into(ctx)
                                .map_err(|e| {
                                    ProbeError::FFiConversionError {
                                        msg: "Error calling ffi_into() on\
                                            #field_idents creating #new_name",
                                        inner: Box::new(e),
                                    }
                                })?,
                            )*
                        })
                    }
                }
            }
            .into()
        }
        _ => unimplemented!("MakeRustOp only supports structs"),
    }
}

fn convert_bindgen_type(ty: &syn::Type) -> syn::Type {
    match ty {
        syn::Type::Ptr(_inner) => parse_quote!(::std::ffi::CString),
        syn::Type::Array(inner) => {
            let mut new = inner.clone();
            new.elem = Box::new(convert_bindgen_type(&new.elem));
            Type::Array(new)
        }
        syn::Type::Path(inner) => {
            if let Some(name) = type_basename(inner).to_string().strip_prefix("C_") {
                let name = Ident::new(name, Span::mixed_site());
                parse_quote!(#name)
            } else {
                Type::Path(inner.clone())
            }
        }
        _ => unimplemented!("unsupported bindgen type conversion"),
    }
}

pub(crate) fn type_basename(ty: &syn::TypePath) -> &syn::Ident {
    if ty.qself.is_some() {
        unimplemented!("qualified self-typs not supported");
    }

    &ty.path.segments.last().expect("type has no segments").ident
}

// TODO: return compiler error instead of panicking on error
#[proc_macro_derive(MakePyDataclass)]
pub fn make_py_dataclass(input: TokenStream) -> TokenStream {
    let source = parse_macro_input!(input as DeriveInput);
    pygen::make_py_dataclass_internal(source);
    // return empty token stream, we're not actually writing rust here
    TokenStream::new()
}
