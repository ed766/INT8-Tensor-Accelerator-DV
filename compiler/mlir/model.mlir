module {
  func.func private @linear_relu(tensor<16x16xi8>) -> tensor<16x4xi8>
  func.func private @linear(tensor<16x4xi8>) -> tensor<16x4xi8>
  func.func @model(%input: tensor<16x16xi8>) -> tensor<16x4xi8>
      attributes {int8.quantization = "signed-i8-nearest-away-saturate-v1"} {
    %hidden = func.call @linear_relu(%input) : (tensor<16x16xi8>) -> tensor<16x4xi8>
    %output = func.call @linear(%hidden) : (tensor<16x4xi8>) -> tensor<16x4xi8>
    return %output : tensor<16x4xi8>
  }
}
