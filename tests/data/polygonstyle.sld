<?xml version='1.0' encoding='UTF-8'?>
<StyledLayerDescriptor xmlns="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.1.0/StyledLayerDescriptor.xsd" version="1.1.0" xmlns:se="http://www.opengis.net/se">
	<NamedLayer>
		<se:Name>trees_18_419_SE-testroi-2022</se:Name>
		<UserStyle>
			<se:Name>trees_18_419_SE-testroi-2022</se:Name>
			<se:FeatureTypeStyle>
				<se:Rule>
					<se:Name>Single symbol</se:Name>
					<se:PolygonSymbolizer>
						<se:Fill>
							<se:GraphicFill>
								<se:Graphic>
									<se:Mark>
										<se:WellKnownName>horline</se:WellKnownName>
										<se:Stroke>
											<se:SvgParameter name="stroke">#0cf600</se:SvgParameter>
											<se:SvgParameter name="stroke-width">1</se:SvgParameter>
										</se:Stroke>
									</se:Mark>
									<se:Size>7</se:Size>
									<se:Rotation>
										<ogc:Literal>45</ogc:Literal>
									</se:Rotation>
								</se:Graphic>
							</se:GraphicFill>
						</se:Fill>
					</se:PolygonSymbolizer>
					<se:LineSymbolizer>
						<se:Stroke>
							<se:SvgParameter name="stroke">#0cf600</se:SvgParameter>
							<se:SvgParameter name="stroke-width">2</se:SvgParameter>
							<se:SvgParameter name="stroke-linejoin">bevel</se:SvgParameter>
							<se:SvgParameter name="stroke-linecap">square</se:SvgParameter>
						</se:Stroke>
					</se:LineSymbolizer>
				</se:Rule>
			</se:FeatureTypeStyle>
		</UserStyle>
	</NamedLayer>
</StyledLayerDescriptor>